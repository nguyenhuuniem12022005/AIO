import os
import json
import math
import copy
from flask import Flask, render_template, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import BadRequestError, OpenAI

load_dotenv()

app = Flask(__name__)
CORS(app)

# FPT Marketplace — cùng endpoint OpenCode / Cline dùng
DEFAULT_BASE_URL = "https://mkp-api.fptcloud.com/v1"
# Model không "thinking": trả lời thẳng vào content, phù hợp budget 2000 token.
# Các model reasoning (Qwen3.6-27B, DeepSeek-V4-Flash, GLM-5.2) đốt hết token
# vào reasoning_content nên content rỗng khi max_tokens nhỏ.
DEFAULT_MODEL = "Llama-3.3-70B-Instruct"
FALLBACK_MODEL = os.getenv("FPT_FALLBACK_MODEL", "gemma-4-31B-it")
MAX_SESSION_TOKENS = int(os.getenv("MAX_SESSION_TOKENS", "2000"))
# Giới hạn mỗi lượt trả lời — 512 hợp lý với budget 2000/session (~3–5 lượt)
MAX_COMPLETION_TOKENS = int(os.getenv("MAX_COMPLETION_TOKENS", "512"))

FPT_BASE_URL = os.getenv("FPT_BASE_URL", DEFAULT_BASE_URL)
FPT_MODEL = os.getenv("FPT_MODEL", DEFAULT_MODEL)
FPT_API_KEY = os.getenv("FPT_API_KEY", "")


def normalize_base_url(url: str) -> str:
    """Đảm bảo base URL kết thúc bằng /v1 (OpenAI-compatible)."""
    url = (url or DEFAULT_BASE_URL).rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def estimate_tokens(text_or_messages):
    """Ước lượng token cho text / messages (~3.2 chars/token, EN+VI)."""
    if isinstance(text_or_messages, str):
        if not text_or_messages:
            return 0
        return max(1, math.ceil(len(text_or_messages) / 3.2))
    if isinstance(text_or_messages, list):
        total = 0
        for msg in text_or_messages:
            content = msg.get("content", "") or ""
            total += 4
            total += estimate_tokens(content)
        return total
    return 0


class ThinkStripper:
    """Ẩn nội dung <think>...</think> khi stream, giữ nguyên phần còn lại."""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self.inside = False
        self.buf = ""

    def _tail_to_hold(self, text: str, tag: str) -> int:
        """Số ký tự cuối cần giữ lại vì có thể là tag bị cắt giữa 2 chunk."""
        lowered = text.lower()
        for size in range(min(len(tag) - 1, len(text)), 0, -1):
            if lowered.endswith(tag[:size]):
                return size
        return 0

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []

        while self.buf:
            if self.inside:
                idx = self.buf.lower().find(self.CLOSE)
                if idx == -1:
                    hold = self._tail_to_hold(self.buf, self.CLOSE)
                    self.buf = self.buf[len(self.buf) - hold:] if hold else ""
                    break
                self.buf = self.buf[idx + len(self.CLOSE):]
                self.inside = False
                continue

            idx = self.buf.lower().find(self.OPEN)
            if idx == -1:
                hold = self._tail_to_hold(self.buf, self.OPEN)
                emit = self.buf[: len(self.buf) - hold] if hold else self.buf
                self.buf = self.buf[len(self.buf) - hold:] if hold else ""
                if emit:
                    out.append(emit)
                break

            if idx:
                out.append(self.buf[:idx])
            self.buf = self.buf[idx + len(self.OPEN):]
            self.inside = True

        return "".join(out)

    def flush(self) -> str:
        leftover = "" if self.inside else self.buf
        self.buf = ""
        self.inside = False
        return leftover


# Giữ ngắn: system prompt bị tính vào prompt_tokens ở MỌI lượt của session.
CHATBOT_SYSTEM = (
    "Bạn là trợ lý AI hữu ích. Trả lời trực tiếp, ngắn gọn, đúng ngôn ngữ người dùng. "
    "Dùng markdown khi cần."
)

# Token tối thiểu chừa cho câu trả lời khi cắt lịch sử
ANSWER_RESERVE_TOKENS = min(256, MAX_COMPLETION_TOKENS)
# Ước lượng có thể thấp hơn thực tế → nhân thêm biên an toàn khi quyết định cắt
TRIM_SAFETY = 1.15


def trim_history(system_msg, history, budget):
    """Cắt bớt lượt cũ nhất để prompt vừa budget còn lại.

    Luôn giữ system prompt và tin nhắn user mới nhất.
    Trả về (messages_đã_cắt, số_tin_nhắn_bị_bỏ).
    """
    kept = list(history)
    dropped = 0

    def fits(msgs):
        est = estimate_tokens([system_msg] + msgs) * TRIM_SAFETY
        return est + ANSWER_RESERVE_TOKENS <= budget

    while len(kept) > 1 and not fits(kept):
        kept.pop(0)
        dropped += 1
        # Tránh mở đầu bằng assistant (mất ngữ cảnh câu hỏi tương ứng)
        if kept and len(kept) > 1 and kept[0].get("role") == "assistant":
            kept.pop(0)
            dropped += 1

    return [system_msg] + kept, dropped


def load_runtime_config():
    # Không override: biến môi trường thật (docker-compose, shell) ưu tiên hơn .env
    load_dotenv()
    return {
        "base_url": normalize_base_url(os.getenv("FPT_BASE_URL", DEFAULT_BASE_URL)),
        "model": os.getenv("FPT_MODEL", DEFAULT_MODEL),
        "fallback_model": os.getenv("FPT_FALLBACK_MODEL", "gemma-4-31B-it"),
        "api_key": os.getenv("FPT_API_KEY", ""),
        "max_session_tokens": int(os.getenv("MAX_SESSION_TOKENS", "2000")),
        "max_completion_tokens": int(os.getenv("MAX_COMPLETION_TOKENS", "512")),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_runtime_config()
    api_key = cfg["api_key"]
    return jsonify({
        "baseUrl": cfg["base_url"],
        "model": cfg["model"],
        "maxSessionTokens": cfg["max_session_tokens"],
        "maxCompletionTokens": cfg["max_completion_tokens"],
        "hasApiKey": bool(api_key and api_key != "your-api-key-here"),
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    cfg = load_runtime_config()
    max_session_tokens = cfg["max_session_tokens"]

    data = request.json or {}
    messages = data.get("messages", [])
    custom_api_key = (data.get("apiKey") or "").strip()
    session_used_tokens = max(0, int(data.get("sessionTokens", 0)))

    api_key = custom_api_key or cfg["api_key"]
    if not api_key or api_key == "your-api-key-here":
        return jsonify({
            "error": "Chưa cấu hình FPT API Key. Nhập key trong Cấu hình hoặc file .env."
        }), 400

    if not messages:
        return jsonify({"error": "Danh sách tin nhắn không được để trống."}), 400

    if session_used_tokens >= max_session_tokens:
        return jsonify({
            "error": (
                f"Session đã hết hạn mức {max_session_tokens} tokens "
                f"(đã dùng {session_used_tokens}). Bấm 'New session' để reset."
            )
        }), 400

    system_msg = {"role": "system", "content": CHATBOT_SYSTEM}
    history = [
        copy.deepcopy(m) for m in messages if m.get("role") in ("user", "assistant")
    ]

    # Budget còn lại của session → cắt lượt cũ để prompt vừa chỗ
    budget = max_session_tokens - session_used_tokens
    api_messages, dropped_messages = trim_history(system_msg, history, budget)

    estimated_prompt = estimate_tokens(api_messages)
    if session_used_tokens + estimated_prompt >= max_session_tokens:
        return jsonify({
            "error": (
                f"Câu hỏi này (~{estimated_prompt} tokens) không còn vừa hạn mức "
                f"{max_session_tokens} tokens/session (đã dùng {session_used_tokens}). "
                "Rút ngắn câu hỏi hoặc bấm 'New session'."
            )
        }), 400

    remaining = max_session_tokens - session_used_tokens - estimated_prompt
    max_completion = cfg["max_completion_tokens"]
    max_tokens_for_model = max(16, min(max_completion, remaining))

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=cfg["base_url"],
            timeout=90.0,
        )

        def generate():
            def sse(payload: dict) -> str:
                return f"data: {json.dumps(payload)}\n\n"

            shown_text = ""
            usage = {"prompt_tokens": 0, "completion_tokens": 0}

            def turn_tokens() -> int:
                """Token thật của lượt này (prompt + completion, theo API FPT)."""
                return usage["prompt_tokens"] + usage["completion_tokens"]

            def open_stream(model_name, with_usage: bool):
                kwargs = {
                    "model": model_name,
                    "messages": api_messages,
                    "temperature": 0.6,
                    "max_tokens": max_tokens_for_model,
                    "top_p": 0.95,
                    "stream": True,
                }
                if with_usage:
                    kwargs["stream_options"] = {"include_usage": True}
                return client.chat.completions.with_streaming_response.create(**kwargs)

            def consume(response):
                """Đọc SSE của FPT: yield text hiển thị, cập nhật usage thật."""
                nonlocal shown_text
                stripper = ThinkStripper()
                stopped = False

                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    body = line[6:].strip()
                    if not body or body == "[DONE]":
                        continue
                    try:
                        payload = json.loads(body)
                    except Exception:
                        continue

                    chunk_usage = payload.get("usage") or {}
                    if chunk_usage.get("prompt_tokens") is not None:
                        usage["prompt_tokens"] = int(chunk_usage["prompt_tokens"])
                    if chunk_usage.get("completion_tokens") is not None:
                        usage["completion_tokens"] = int(
                            chunk_usage["completion_tokens"]
                        )

                    choices = payload.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        piece = delta.get("content") or ""
                        if piece:
                            visible = stripper.feed(piece)
                            if visible:
                                shown_text += visible
                                yield sse({"content": visible})

                    # Chốt cứng: dừng ngay khi token thật đụng hạn mức
                    if session_used_tokens + turn_tokens() >= max_session_tokens:
                        stopped = True
                        break

                if not stopped:
                    leftover = stripper.flush()
                    if leftover:
                        shown_text += leftover
                        yield sse({"content": leftover})

            def stream_model(model_name):
                """Ưu tiên stream_options (usage chính xác); fallback nếu bị từ chối."""
                try:
                    with open_stream(model_name, True) as response:
                        yield from consume(response)
                except BadRequestError:
                    if shown_text:
                        raise
                    with open_stream(model_name, False) as response:
                        yield from consume(response)

            try:
                models_to_try = [cfg["model"]]
                if cfg["fallback_model"] and cfg["fallback_model"] != cfg["model"]:
                    models_to_try.append(cfg["fallback_model"])

                for model_name in models_to_try:
                    yield from stream_model(model_name)
                    # Model reasoning không trả content → thử model instruct dự phòng
                    if shown_text.strip():
                        break
                    usage["prompt_tokens"] = 0
                    usage["completion_tokens"] = 0

                if not shown_text.strip():
                    shown_text = (
                        "_(Model này chỉ trả về phần suy luận nội bộ. "
                        "Hãy đổi `FPT_MODEL` sang model instruct, ví dụ "
                        "`Llama-3.3-70B-Instruct` hoặc `gemma-4-31B-it`.)_"
                    )
                    yield sse({"content": shown_text, "replace": True})

                new_session_total = min(
                    max_session_tokens, session_used_tokens + turn_tokens()
                )
                yield sse({
                    "done": True,
                    "promptTokens": usage["prompt_tokens"],
                    "completionTokens": usage["completion_tokens"],
                    "turnTokens": turn_tokens(),
                    "newSessionTotal": new_session_total,
                    "maxSessionTokens": max_session_tokens,
                    "limitReached": new_session_total >= max_session_tokens,
                    "droppedMessages": dropped_messages,
                    "exact": True,
                })

            except Exception as stream_err:
                yield sse({
                    "content": f"Lỗi FPT API: {stream_err}",
                    "replace": True,
                })
                yield sse({
                    "done": True,
                    "promptTokens": 0,
                    "completionTokens": 0,
                    "turnTokens": 0,
                    "newSessionTotal": session_used_tokens,
                    "maxSessionTokens": max_session_tokens,
                    "limitReached": False,
                })

        return Response(generate(), mimetype="text/event-stream")

    except Exception as e:
        return jsonify({"error": f"Lỗi FPT Cloud API: {str(e)}"}), 500


if __name__ == "__main__":
    print("[+] FPT AI Chatbot → http://localhost:5000")
    print(
        f"[*] Model: {FPT_MODEL} | Base: {normalize_base_url(FPT_BASE_URL)} "
        f"| Session cap: {MAX_SESSION_TOKENS} tokens"
    )
    app.run(host="0.0.0.0", port=5000, debug=True)

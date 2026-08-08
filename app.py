import os
import json
import math
from flask import Flask, render_template, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration defaults
FPT_BASE_URL = os.getenv("FPT_BASE_URL", "https://mkp-api.fptcloud.com")
FPT_MODEL = os.getenv("FPT_MODEL", "Qwen3.6-27B")
FPT_API_KEY = os.getenv("FPT_API_KEY", "")
MAX_SESSION_TOKENS = int(os.getenv("MAX_SESSION_TOKENS", 2000))

def estimate_tokens(text_or_messages):
    """
    Estimates token count for text or list of OpenAI message objects.
    Approximation for Qwen / multilingual models (~3.5 chars/token).
    """
    if isinstance(text_or_messages, str):
        if not text_or_messages:
            return 0
        # Roughly 3.5 characters per token for mixed English/Vietnamese text
        return max(1, math.ceil(len(text_or_messages) / 3.2))
    elif isinstance(text_or_messages, list):
        total = 0
        for msg in text_or_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            total += 4 # Overhead for message metadata/role
            total += estimate_tokens(content)
        return total
    return 0

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    load_dotenv(override=True)
    fpt_api_key = os.getenv("FPT_API_KEY", "")
    return jsonify({
        "baseUrl": os.getenv("FPT_BASE_URL", "https://mkp-api.fptcloud.com"),
        "model": os.getenv("FPT_MODEL", "Qwen3.6-27B"),
        "maxSessionTokens": int(os.getenv("MAX_SESSION_TOKENS", 2000)),
        "hasApiKey": bool(fpt_api_key and fpt_api_key != "your-api-key-here")
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    load_dotenv(override=True)
    fpt_base_url = os.getenv("FPT_BASE_URL", "https://mkp-api.fptcloud.com")
    fpt_model = os.getenv("FPT_MODEL", "Qwen3.6-27B")
    fpt_api_key = os.getenv("FPT_API_KEY", "")
    max_session_tokens = int(os.getenv("MAX_SESSION_TOKENS", 2000))

    data = request.json or {}
    messages = data.get("messages", [])
    custom_api_key = data.get("apiKey", "").strip()
    session_used_tokens = int(data.get("sessionTokens", 0))

    api_key = custom_api_key if custom_api_key else fpt_api_key
    if not api_key or api_key == "your-api-key-here":
        return jsonify({
            "error": "Chưa cấu hình FPT API Key. Vui lòng nhập API Key trong phần Cấu hình hoặc file .env!"
        }), 400

    if not messages:
        return jsonify({"error": "Danh sách tin nhắn không được để trống!"}), 400

    # System prompt: trợ lý hỗ trợ Olympic AI, trả lời đúng ngôn ngữ người dùng
    system_prompt = {
        "role": "system",
        "content": (
            "/no_think\n"  # Tắt thinking mode của Qwen3 & GLM
            "Bạn là trợ lý AI chuyên hỗ trợ thí sinh tham gia cuộc thi Olympic AI. "
            "Bạn có kiến thức sâu về: lập trình, thuật toán, machine learning, deep learning, "
            "toán học, thống kê và các chủ đề liên quan đến AI. "
            "Hãy LUÔN trả lời bằng ĐÚNG ngôn ngữ mà người dùng sử dụng "
            "(hỏi tiếng Việt → trả lời tiếng Việt, hỏi tiếng Anh → trả lời tiếng Anh). "
            "Trả lời trực tiếp, chính xác, không hiển thị quá trình suy nghĩ nội bộ."
        )
    }
    # Chỉ thêm system prompt nếu chưa có
    if not messages or messages[0].get("role") != "system":
        messages = [system_prompt] + messages

    # Chỉ tính token của tin nhắn MỚI NHẤT (session_used_tokens đã đếm lịch sử rồi)
    new_message_content = messages[-1].get("content", "") if messages else ""
    prompt_tokens = estimate_tokens(new_message_content)
    current_total_tokens = session_used_tokens + prompt_tokens

    if current_total_tokens >= max_session_tokens:
        return jsonify({
            "error": f"Phiên làm việc này đã dùng {session_used_tokens} tokens. Tin nhắn mới ({prompt_tokens} tokens) vượt quá hạn mức {max_session_tokens} tokens/session. Vui lòng bấm 'Tạo phiên mới' để tiếp tục!"
        }), 400

    remaining_tokens = max_session_tokens - current_total_tokens
    max_tokens_for_model = min(1024, max(300, remaining_tokens))

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=fpt_base_url,
            timeout=60.0  # 60 giây timeout, tránh treo mãi
        )

        def generate():
            completion_text = ""

            # Dùng raw HTTP stream để đọc được field reasoning_content của GLM
            # OpenAI SDK bỏ qua field này nên phải đọc JSON thô
            with client.chat.completions.with_streaming_response.create(
                model=fpt_model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens_for_model,
                top_p=0.95,
                stream=True
            ) as response:
                for line in response.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        # Qwen dùng content, GLM dùng reasoning_content
                        chunk_text = delta.get("content") or delta.get("reasoning_content") or ""
                        if chunk_text:
                            completion_text += chunk_text
                            yield f"data: {json.dumps({'content': chunk_text})}\n\n"
                    except Exception:
                        continue

            # Tính token sau khi stream xong
            completion_tokens = estimate_tokens(completion_text)
            new_session_total = current_total_tokens + completion_tokens
            yield f"data: {json.dumps({'done': True, 'promptTokens': prompt_tokens, 'completionTokens': completion_tokens, 'newSessionTotal': new_session_total})}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    except Exception as e:
        return jsonify({"error": f"Lỗi từ FPT Cloud API: {str(e)}"}), 500

if __name__ == "__main__":
    print("[+] FPT Cloud AI Chatbot Server running on http://localhost:5000")
    print(f"[*] Model: {FPT_MODEL} | Base URL: {FPT_BASE_URL} | Session Token Limit: {MAX_SESSION_TOKENS}")
    app.run(host="0.0.0.0", port=5000, debug=True)

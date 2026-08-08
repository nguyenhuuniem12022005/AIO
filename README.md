# FPT AI Chatbot

Web chatbot hội thoại kiểu ChatGPT / Gemini, chạy trên **FPT AI Marketplace** (OpenAI-compatible API). Mỗi phiên giới hạn **2000 tokens**.

| Field | Value |
|--------|--------|
| Base URL | `https://mkp-api.fptcloud.com/v1` |
| Model | `Llama-3.3-70B-Instruct` |
| Auth | `Authorization: Bearer <API_KEY>` |
| Session cap | `MAX_SESSION_TOKENS=2000` |

---

## Tính năng

- Trả lời streaming từng chữ (SSE), markdown + highlight code
- Thanh đếm `X / 2000` tokens, khóa input khi hết budget
- **New session** — reset hội thoại và token về 0
- Ẩn hoàn toàn phần suy luận nội bộ (`reasoning_content`, `<think>`) khỏi UI
- API Key qua `.env` hoặc modal trên UI (lưu localStorage)

---

## Cách đếm 2000 tokens/session

Không dùng ước lượng — lấy **`usage` thật** do API FPT trả về trong stream
(`stream_options: {include_usage: true}`).

Mỗi lượt cộng vào budget: `prompt_tokens + completion_tokens`. Trong đó
`prompt_tokens` gồm system prompt + toàn bộ lịch sử hội thoại được gửi lại,
đúng như FPT tính phí.

Bốn lớp bảo vệ để không bao giờ vượt 2000:

1. **Tự cắt lịch sử** — khi budget còn ít, các lượt cũ nhất bị bỏ khỏi prompt
   (luôn giữ system prompt + câu hỏi mới nhất) để vẫn chat tiếp được.
2. **Trước khi gọi API** — nếu prompt vẫn không vừa thì chặn kèm thông báo rõ ràng.
3. **Khi gọi API** — `max_tokens` đặt bằng đúng phần budget còn lại.
4. **Trong lúc stream** — theo dõi `usage` từng chunk, đụng hạn mức là dừng ngay.

Dưới mỗi câu trả lời có dòng chi phí thật của lượt đó:
`+N tokens (prompt X · trả lời Y) · còn Z`, kèm số tin nhắn cũ đã cắt nếu có.

System prompt được giữ rất ngắn vì nó bị tính lại ở **mọi** lượt trong session.

---

## Chọn model — quan trọng

Dùng **model instruct** (trả lời trực tiếp). Các model reasoning tiêu hết token cho phần suy luận nội bộ, nên với budget 2000 tokens sẽ không kịp sinh câu trả lời:

| Model | Phù hợp? |
|--------|-----------|
| `Llama-3.3-70B-Instruct` | Có — mặc định |
| `gemma-4-31B-it` | Có |
| `gemma-3-27b-it` | Có |
| `Qwen3.6-27B` | Không — reasoning model |
| `DeepSeek-V4-Flash` | Không — reasoning model |
| `GLM-5.2` | Không — reasoning model |

Nếu model chính không trả về nội dung, app tự thử lại với `FPT_FALLBACK_MODEL`.

---

## Chạy local

### 1. `.env`

```bash
cp .env.example .env
```

```env
FPT_BASE_URL=https://mkp-api.fptcloud.com/v1
FPT_MODEL=Llama-3.3-70B-Instruct
FPT_FALLBACK_MODEL=gemma-4-31B-it
FPT_API_KEY=sk-your-fpt-api-key
MAX_SESSION_TOKENS=2000
```

Tạo key tại [marketplace.fptcloud.com](https://marketplace.fptcloud.com/).

### 2. Python

```bash
pip install -r requirements.txt
python app.py
```

Mở [http://localhost:5000](http://localhost:5000).

---

## Docker

```bash
docker compose up -d --build
```

hoặc:

```bash
docker build -t fpt-ai-chatbot .
docker run -d -p 5000:5000 --env-file .env --name fpt_chatbot fpt-ai-chatbot
```

Xem log:

```bash
docker compose logs -f
```

---

## Vercel

```bash
npx vercel
```

Env trên Vercel:

- `FPT_BASE_URL` = `https://mkp-api.fptcloud.com/v1`
- `FPT_MODEL` = `Llama-3.3-70B-Instruct`
- `FPT_API_KEY` = key của bạn
- `MAX_SESSION_TOKENS` = `2000`

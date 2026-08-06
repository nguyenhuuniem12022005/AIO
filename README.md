# 🤖 FPT Cloud AI Web Chatbot (ChatGPT-like UI)

Ứng dụng Web Chatbot giao diện ChatGPT-like miễn phí kết nối với **FPT Cloud API** (Model: `GLM-5.2` / `Qwen3.6-27B`) với tính năng giới hạn và đếm **2000 tokens/session**.

---

## ✨ Tính năng nổi bật

- 🎨 **Giao diện ChatGPT-like**: Modern Dark Theme (Obsidian & Emerald accent), phản hồi gõ chữ real-time (Server-Sent Events streaming).
- ⚡ **Thanh Đếm Token Trực Quan**: Hiển thị `X / 2000 Tokens` theo từng lượt hỏi đáp, tự động đổi màu cảnh báo (Green -> Yellow -> Red) và khóa ô chat khi vượt hạn mức 2000 token.
- 🔄 **Nút Tạo Phiên Mới**: Reset token về 0 và làm sạch hội thoại cho bài luyện tập tiếp theo.
- 📝 **Markdown & Code Highlighting**: Tô màu code block tự động với nút copy code tiện lợi.
- 🐳 **Hỗ trợ Docker & Docker Compose**: Đóng gói sẵn sàng chạy container trên server/vps với 1 câu lệnh.

---

## 🛠️ Hướng dẫn Chạy cục bộ (Local)

### 1. Cấu hình file `.env`
Sao chép `.env.example` thành `.env` và cập nhật API Key của bạn:
```env
FPT_BASE_URL=https://mkp-api.fptcloud.com
FPT_MODEL=GLM-5.2
FPT_API_KEY=sk-your-fpt-api-key-here
MAX_SESSION_TOKENS=2000
```

### 2. Khởi chạy bằng Python
```bash
pip install -r requirements.txt
python app.py
```
Mở trình duyệt tại [http://localhost:5000](http://localhost:5000).

---

## 🐳 Khởi chạy bằng Docker / Docker Compose

### Cách 1: Sử dụng Docker Compose (Khuyên dùng)
```bash
docker compose up -d --build
```

### Cách 2: Sử dụng Docker CLI
```bash
# Build image
docker build -t fpt-ai-chatbot .

# Run container
docker run -d -p 5000:5000 --env-file .env --name fpt_chatbot fpt-ai-chatbot
```

---

## 🚀 Triển khai lên Vercel

```bash
npx vercel
```
Hoặc kết nối Repository GitHub này với [Vercel](https://vercel.com) và thêm các biến môi trường trong **Project Settings > Environment Variables**:
- `FPT_BASE_URL` = `https://mkp-api.fptcloud.com`
- `FPT_MODEL` = `GLM-5.2`
- `FPT_API_KEY` = `your-api-key`
- `MAX_SESSION_TOKENS` = `2000`

# PhantomCustom — by Lê Tiến Dũng

Nền tảng web treo tool đa tài khoản (Discord · Zalo · Messenger) chạy 24/7 trên Render.

## Tính năng

- **6 tool** bám sát 100% chức năng tool gốc:
  - `treodis` — Treo Discord: nhiều token + nhiều channel + delay.
  - `nhaydiscord` — Nhây Discord: token + UID channel, chạy liên tục.
  - `treozalo` — Treo Zalo: IMEI + session cookie, text/ảnh/video, mention, style, TTL.
  - `treomess` — Treo Messenger: nhiều cookie + nhiều box + đa tài khoản luân phiên.
  - `nhaymess` — Nhây Messenger: fake typing MQTT + tag mention.
  - `zalomulti` — Zalo đa năng: nhaytag, treongon, spamcall, treoanh, đổi tên/avatar nhóm, sticker, voice, card, join.
- Mỗi user chạy **nhiều task song song**, quản lý: xem uptime realtime, tạm dừng, tiếp tục, dừng, xoá, xem log, **thay cookie/IMEI/token/UID/box** ngay khi đang chạy.
- **Lưu trữ bền vững**: task lưu SQLite, logout/login lại vẫn còn, server restart tự khôi phục task đang chạy.
- **Admin panel**: xem toàn bộ user, xem mọi task, đóng task từ xa, cấp quyền 1 tuần / 1 tháng / 1 năm / vĩnh viễn, khoá user, phát thông báo toàn hệ thống.
- **Chặn user chưa thuê**: hiện thông báo thuê qua Zalo **0969411158** / Discord **dleecte**.
- Giao diện đen–trắng gradient, chữ động, tuyết rơi, chibi anime, nhạc chill, glassmorphism.

## Tài khoản admin

```
username: dungledev
password: dunglengaongo
```

## Chạy local

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Mở http://localhost:8000

## Deploy lên Render

1. Push thư mục này lên GitHub.
2. Vào Render → **New → Web Service** → chọn repo.
3. Render tự đọc `render.yaml` (hoặc điền tay):
   - Build: `pip install --no-cache-dir -r requirements.txt`
   - Start: `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1`
4. Deploy. Render cấp URL dạng `https://phantomcustom.onrender.com`.

> Gói free Render sẽ "ngủ" khi không có traffic. Để treo 24/7 thật sự, dùng gói trả phí hoặc bật uptime monitor ping mỗi 5 phút. Kiến trúc ở đây nhẹ (thread + SQLite WAL) nên RAM thấp, không tạo process nặng cho mỗi task.

## Nhạc nền

- Mặc định phát `static/music.wav` (ambient chill tạo sẵn).
- Muốn phát bài **“10 ngàn năm”**: bỏ file `music.mp3` vào `static/`, web sẽ ưu tiên file này.

## Ghi chú kỹ thuật

- Task chạy bằng thread nhẹ, có `stop_event` / `pause_event`, không rò rỉ process.
- Cấu hình task (cookie/token/UID/box...) lưu JSON trong SQLite, sửa trực tiếp qua nút ⚙ Sửa.
- Tool Zalo dùng `zlapi`, Messenger dùng HTTP + MQTT, Discord dùng REST API v10.
- Mọi tool import thư viện ở chế độ an toàn: thiếu lib sẽ báo log chứ không làm sập server.

## Liên hệ thuê

- Zalo: **0969411158**
- Discord: **dleecte**

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

## 🆕 Cập nhật mới
- **Giao diện mobile**: responsive đầy đủ cho điện thoại (header, tool grid, task, bảng admin cuộn ngang, modal).
- **Mascot anime GIF động thật**: lấy GIF anime chibi từ Pinterest/Tenor (cute-honey-senpai, chibi-anime-boy, mèo mochi, anime wave) — không tự vẽ.
- **Facebook: Lấy UID & Box từ cookie** — nút "🔎 UID & Box FB" trong Bảng điều khiển:
  - Nhập cookie Facebook → trả về **UID**, **tên hiển thị**, và **danh sách box** (nhóm/chat) kèm nút copy từng ID hoặc copy tất cả.
  - Endpoint: `POST /api/fb/info` (body `{"cookie": "..."}`).

## 🎵 Nhạc nền
- Bài **"10 ngàn năm | PC [Prod. Duckie] (slowed)"** (SoundCloud) — `static/music.mp3` (3:59) + ảnh cover `static/music-cover.jpg`.
- Tự phát sau lần click đầu tiên (chính sách autoplay của trình duyệt), có dock nhỏ hiển thị cover + tên bài + nút bật/tắt.

## 🔎 Facebook UID & Box — chi tiết kỹ thuật
- `POST /api/fb/info` → `{uid, name, boxes:[{id,name,type,count,snippet}], count, note}`
- Dùng full browser headers (Chrome 124) + `fb_dtsg`/`lsd` + GraphQL `MessengerThreadList` (doc_id `1349387578499440`), fallback parse HTML mbasic/mobile.
- Tên box lấy từ `name` hoặc ghép tên `all_participants` (bỏ chính chủ tài khoản).

## 🩺 Sửa lỗi đăng nhập
- Trước đây `bootUser()` đăng xuất cả khi lỗi mạng/máy chủ → "báo thành công nhưng không vào được".
- Nay chỉ đăng xuất khi HTTP 401 thật; lỗi mạng sẽ **tự thử lại 3 lần** và báo rõ.

---

## 🆕 Bản cập nhật: DNB Team · Check Live/Die · Nhập acc từ .txt · Chống die acc

### 1. Thương hiệu
- Dưới logo **PhantomCustom** đã thêm dòng **BY LÊ TIẾN DŨNG · DNB TEAM**.
- Hero có thêm dòng **DNB TEAM · by Lê Tiến Dũng**.
- Thêm **marquee chạy ngang**: “Tool này được **Dũng Lê** bên **DNB Team** phát triển — hiện đại nhất hiện nay” + các dòng giới thiệu tool.

### 2. Nhập full acc từ file .txt (không cần nhập tay)
- Mỗi ô danh sách (tokens, cookies, groups, threads, members, messages…) đều có nút **📁 .txt** ở góc dưới phải.
- Bấm → chọn file `.txt` → nội dung được **nối thêm** vào ô đó (không ghi đè dữ liệu đang có).
- Vẫn có thể dán/nhập tay bình thường — tuỳ người dùng.
- Tool tự tách theo dòng nên 1 task có thể treo **hàng trăm acc** cùng lúc.

### 3. Check Live/Die hàng loạt (`/api/check`)
Nút **🧪 Check Live/Die** trong Dashboard. 4 loại:

| Loại | Cách nhập | Kết quả trả về |
|---|---|---|
| `discord` | mỗi dòng 1 token | LIVE/DIE + tên, UID, email, SĐT, verify |
| `fb_cookie` | mỗi dòng 1 cookie (`c_user=…; xs=…`) | LIVE/DIE + UID + tên |
| `fb_link` | mỗi dòng 1 link / username / UID | LIVE/DIE + tên trang |
| `zalo` | `imei\|cookie_json` mỗi dòng, **hoặc** file export có dòng `IMEI:` | LIVE/DIE + tên, UID, SĐT |

- Tải file `.txt` trực tiếp trong modal (FileReader, không upload lên server).
- Ô **Cookie Facebook** (tuỳ chọn) giúp check link chính xác 100% (FB chặn xem ẩn danh).
- Tổng kết: **X acc · Y LIVE · Z DIE · W chưa xác định**, có nút **Copy acc LIVE** và Copy từng dòng.
- Chỉ đọc thông tin, **không gửi tin nhắn**, không ảnh hưởng acc.

### 4. Cấu trúc treo trụ + chống die acc (áp dụng MỌI tool)
Mỗi task có thêm khối **🛡 Cấu trúc treo trụ · chống die acc**:
- `jitter` — delay ngẫu nhiên ±% (mặc định 25%) → không gửi đều tăm tắp như bot.
- `rest_every` — nghỉ sau mỗi N lần gửi (mặc định 40).
- `rest_time` — thời gian nghỉ (mặc định 30s), có log “🛡 Nghỉ bảo vệ acc”.
- `max_sent` — tự dừng sau N tin (0 = không giới hạn).

Các tham số gốc của từng tool **giữ nguyên 100%** (api_key, secret_key, imei, cookies, ttl, colors, media_type, mode 10 chế độ Zalo, typing MQTT, mention…). Lớp chống die được chèn ở tầng `TaskContext.wait()` nên mọi tool đều hưởng.

### 5. Kết quả test thật
- Discord token của bạn: **LIVE** — `Dũng Lê` · `1352998568713261158` · `dungledzaim@gmail.com` · `+84369899314`.
- Zalo (IMEI `b84aaf8f3e411c94` + cookie JSON trong file export): **LIVE** — `Le Tien Dung Cte` · UID `631712237950777903` · `+84369899314`.
- Facebook cookie: **LIVE** — `Le Hoang Minh Dung` · UID `61595840612546`.
- Cookie giả `c_user=100000000000001` → **DIE** đúng.
- Link `zuck`, `facebook` → LIVE; username rác → DIE.

## 🚀 Deploy chính thức (Render · 24/7)
- Repo: https://github.com/dungledzai1-design/phantomcustom
- Live: **https://phantomcustom.onrender.com**
- Health check: `/healthz`
- Start: `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1`

### Cập nhật: Zalo chỉ cần IMEI + cookie
Đã bỏ hoàn toàn ô `api_key` / `secret_key` khỏi form **Treo Zalo** và **Zalo Đa Năng**.
Người dùng chỉ cần dán **IMEI** + **session cookie** (JSON hoặc chuỗi) là task chạy được.
Các tool khác cũng chỉ cần đúng 1 loại thông tin đăng nhập:
- Treo Discord / Nhây Discord → **token** (+ channel, nội dung)
- Treo Messenger / Nhây Messenger → **cookie FB**
- Treo Zalo / Zalo Đa Năng → **IMEI + cookie**
- Check Live/Die → **token Discord**, **cookie FB**, **link FB**, **IMEI|cookie Zalo**

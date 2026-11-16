"""Bot Telegram điều khiển web PhantomCustom từ xa + nhận thông báo.

Env (đặt trong Render → Environment):
  TELE_BOT_TOKEN = token bot (BotFather)
  TELE_ADMIN_ID  = chat_id Telegram của admin (lệnh chỉ chạy từ đây)
                   — nếu chưa set: người đầu tiên nhắn /start cho bot
                   sẽ được tự lưu làm admin (lưu trong bảng bot_admins)

Lệnh admin:
  /users              — tất cả người dùng (ID, tên, quyền, ngày đăng ký, login cuối)
  /info <id>          — chi tiết 1 user
  /grant <id> <gói>   — week|month|year|forever|revoke
  /del <id> [ok]      — xoá user (gõ /del <id> ok để xác nhận)
  /stats              — tổng quan hệ thống

Tự động: thông báo user mới đăng ký / user bị xoá / cấp quyền tới admin chat.
"""
import os
import time
import threading
import traceback

import requests

import database as db

API = "https://api.telegram.org"


def _token():
    return os.environ.get("TELE_BOT_TOKEN", "").strip()


def _admin_id():
    try:
        return int(os.environ.get("TELE_ADMIN_ID", "").strip())
    except ValueError:
        return 0


def _admin_chats():
    """Danh sách chat_id admin: env ưu tiên; nếu chưa set env thì lấy từ DB
    (admin đầu tiên nhắn /start cho bot sẽ được tự lưu)."""
    env = _admin_id()
    if env:
        return [env]
    try:
        return [a["chat_id"] for a in db.list_bot_admins()]
    except Exception:
        return []


def _is_admin(chat):
    return chat in _admin_chats()


def _api(method, **data):
    try:
        r = requests.post(f"{API}/bot{_token()}/{method}", json=data, timeout=70)
        return r.json() if r.status_code == 200 else {"ok": False}
    except Exception:
        return {"ok": False}


def notify(text):
    """Gửi thông báo tới tất cả admin (im lặng nếu chưa cấu hình / lỗi mạng)."""
    if not _token():
        return False
    ok = False
    for chat in _admin_chats():
        res = _api("sendMessage", chat_id=chat, text=text[:4000],
                   parse_mode="HTML", disable_web_page_preview=True)
        ok = ok or bool(res.get("ok"))
    return ok


# ---------------- helpers chia sẻ ----------------
GRANT_TABLE = {"week": (7, "1 tuần"), "month": (30, "1 tháng"), "year": (365, "1 năm")}


def do_grant(uid, duration):
    """Trả về (ok, message) — dùng chung logic với endpoint /grant của web."""
    target = db.get_user(uid)
    if not target:
        return False, f"Không tìm thấy user #{uid}"
    if duration == "forever":
        until, label = 4102444800, "Vĩnh viễn"
    elif duration == "revoke":
        until, label = 0, "none"
    elif duration in GRANT_TABLE:
        days, label = GRANT_TABLE[duration]
        until, label = time.time() + days * 86400, label
    else:
        return False, "Gói không hợp lệ: week|month|year|forever|revoke"
    db.update_user(uid, access_until=until, access_label=label)
    try:
        from backup import schedule_soon
        schedule_soon()
    except Exception:
        pass
    return True, f"✅ Đã cấp quyền <b>{label}</b> cho {target['username']} (#{uid})"


def do_delete(uid):
    """Xoá user + task + session (giống endpoint DELETE admin). Trả về message."""
    target = db.get_user(uid)
    if not target:
        return f"Không tìm thấy user #{uid}"
    try:
        from task_manager import manager
        manager.delete_all_user(uid)
    except Exception:
        pass
    ok = db.delete_user(uid)
    if ok:
        try:
            from backup import schedule_soon
            schedule_soon()
        except Exception:
            pass
        return f"🗑 Đã xoá <b>{target['username']}</b> (#{uid}) + toàn bộ task của họ"
    return "Xoá thất bại"


# ---------------- format ----------------
def _fmt_dt(ts):
    if not ts:
        return "—"
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))


def _access_line(u):
    if u.get("banned"):
        return "🚫 BANNED"
    if not u.get("access_until"):
        return "❌ Chưa có quyền"
    if u["access_until"] > time.time():
        con_lai = int(u["access_until"] - time.time())
        ngay = con_lai // 86400
        return f"✅ {u['access_label']} — còn {ngay} ngày ({_fmt_dt(u['access_until'])})"
    return f"⌛ {u['access_label']} — ĐÃ HẾT HẠN ({_fmt_dt(u['access_until'])})"


def cmd_users():
    users = db.list_users()
    if not users:
        return "Chưa có user nào."
    lines = [f"👥 <b>{len(users)} người dùng:</b>"]
    for u in users:
        line = (f"<b>#{u['id']}</b> {u['username']}"
                + (" 👑" if u.get("is_admin") else "")
                + f"\n   {_access_line(u)}")
        if u.get("last_login"):
            line += f" | đăng nhập: {_fmt_dt(u['last_login'])}"
        lines.append(line)
    return "\n".join(lines)


def cmd_info(uid):
    u = db.get_user(uid)
    if not u:
        return f"Không tìm thấy user #{uid}"
    tasks = []
    try:
        from task_manager import manager
        tasks = manager.list_for_user(uid)
    except Exception:
        pass
    running = sum(1 for t in tasks if t.get("status") == "running")
    return (f"👤 <b>{u['username']}</b> (#{u['id']})\n"
            f"Quyền: {_access_line(u)}\n"
            f"Admin: {'có' if u.get('is_admin') else 'không'} | Banned: {'có' if u.get('banned') else 'không'}\n"
            f"Đăng ký: {_fmt_dt(u.get('created_at'))}\n"
            f"Đăng nhập cuối: {_fmt_dt(u.get('last_login'))}\n"
            f"Task: {running} đang chạy / {len(tasks)} tổng")


def cmd_stats():
    users = db.list_users()
    try:
        from task_manager import manager
        all_tasks = manager.list_all()
    except Exception:
        all_tasks = []
    running = sum(1 for t in all_tasks if t.get("status") == "running")
    today = time.time() - 86400
    moi = sum(1 for u in users if u.get("created_at", 0) > today)
    co_quyen = sum(1 for u in users if u.get("access_until", 0) > time.time())
    return (f"📊 <b>Thống kê hệ thống</b>\n"
            f"👥 User: {len(users)} (mới 24h: {moi} | còn quyền: {co_quyen})\n"
            f"⚙️ Task: {len(all_tasks)} (đang chạy: {running})")


def handle_update(upd):
    msg = upd.get("message") or {}
    chat = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    sender = (msg.get("from") or {}).get("username", "")
    if not text or not chat:
        return

    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    # chưa có admin nào (chưa set TELE_ADMIN_ID và DB trống) → người /start đầu tiên làm admin
    if not _admin_chats():
        if cmd == "/start":
            db.add_bot_admin(chat, sender)
            _api("sendMessage", chat_id=chat, parse_mode="HTML", disable_web_page_preview=True, text=(
                f"🤖 <b>Bạn đã trở thành admin của bot!</b>\n"
                f"Chat ID: <code>{chat}</code> (nên đặt thêm vào env TELE_ADMIN_ID trên Render)\n\n"
                "/users — tất cả người dùng\n"
                "/info &lt;id&gt; — chi tiết 1 user\n"
                "/grant &lt;id&gt; week|month|year|forever|revoke — cấp/thu hồi quyền\n"
                "/del &lt;id&gt; ok — xoá user (cần gõ ok để xác nhận)\n"
                "/stats — thống kê hệ thống\n\n"
                "Tự động thông báo tới bạn: 🆕 user đăng ký, 🗑 user bị xoá, ✅ cấp quyền, "
                "và mọi hành động admin trên web."))
            return
        _api("sendMessage", chat_id=chat, text=(
            f"⛔ Bot chưa có admin. Chủ web nhắn /start để đăng ký "
            f"(Chat ID của bạn: {chat})."))
        return

    if not _is_admin(chat):
        _api("sendMessage", chat_id=chat, text="⛔ Bot chỉ phục vụ admin.")
        return

    if cmd in ("/start", "/help"):
        _api("sendMessage", chat_id=chat, parse_mode="HTML", disable_web_page_preview=True, text=(
            f"🤖 <b>Bot PhantomCustom</b>\nChat ID của bạn: <code>{chat}</code>\n\n"
            "/users — tất cả người dùng\n"
            "/info &lt;id&gt; — chi tiết 1 user\n"
            "/grant &lt;id&gt; week|month|year|forever|revoke — cấp/thu hồi quyền\n"
            "/del &lt;id&gt; ok — xoá user (cần gõ ok để xác nhận)\n"
            "/stats — thống kê hệ thống\n\n"
            "Tự động thông báo: 🆕 user đăng ký, 🗑 user bị xoá, ✅ cấp quyền, "
            "và mọi hành động admin trên web."))
    elif cmd == "/users":
        _api("sendMessage", chat_id=chat, text=cmd_users(), parse_mode="HTML",
             disable_web_page_preview=True)
    elif cmd == "/info" and len(args) >= 1:
        try:
            _api("sendMessage", chat_id=chat, text=cmd_info(int(args[0])), parse_mode="HTML")
        except ValueError:
            _api("sendMessage", chat_id=chat, text="Dùng: /info <id>")
    elif cmd == "/grant" and len(args) >= 2:
        try:
            ok, msg2 = do_grant(int(args[0]), args[1].lower())
            if ok:
                notify(f"✅ <b>Cấp quyền qua Telegram</b>\n{msg2}")
            _api("sendMessage", chat_id=chat, text=msg2, parse_mode="HTML")
        except ValueError:
            _api("sendMessage", chat_id=chat, text="Dùng: /grant <id> week|month|year|forever|revoke")
    elif cmd == "/del":
        if len(args) >= 2 and args[1].lower() == "ok":
            try:
                m = do_delete(int(args[0]))
            except ValueError:
                m = "Dùng: /del <id> ok"
            notify(f"🗑 <b>Xoá user qua Telegram</b>\n{m}")
            _api("sendMessage", chat_id=chat, text=m, parse_mode="HTML")
        elif len(args) >= 1:
            try:
                u = db.get_user(int(args[0]))
                if u:
                    _api("sendMessage", chat_id=chat,
                         text=f"⚠️ Sắp xoá <b>{u['username']}</b> (#{u['id']}) + toàn bộ task của họ.\nGõ lại: <code>/del {u['id']} ok</code> để xác nhận!",
                         parse_mode="HTML")
                else:
                    _api("sendMessage", chat_id=chat, text=f"Không tìm thấy user #{args[0]}")
            except ValueError:
                _api("sendMessage", chat_id=chat, text="Dùng: /del <id> ok")
        else:
            _api("sendMessage", chat_id=chat, text="Dùng: /del <id> ok")
    elif cmd == "/stats":
        _api("sendMessage", chat_id=chat, text=cmd_stats(), parse_mode="HTML")


def _poll_loop(offset_box):
    offset = offset_box[0]
    while True:
        try:
            r = requests.get(f"{API}/bot{_token()}/getUpdates",
                             params={"offset": offset, "timeout": 25},
                             timeout=40)
            data = r.json()
            for upd in data.get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                try:
                    handle_update(upd)
                except Exception:
                    traceback.print_exc()
            offset_box[0] = offset
        except Exception:
            time.sleep(10)


def start():
    """Bật luồng poll tin nhắn. Trả về True nếu cấu hình đủ."""
    if not (_token() and _admin_chats()):
        return False
    box = [0]
    threading.Thread(target=_poll_loop, args=(box,), daemon=True).start()
    me = _api("getMe").get("result", {})
    print(f"[tgbot] polling đã bật: @{me.get('username')} → admin chat {_admin_chats()}")
    return True

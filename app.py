"""PhantomCustom by Lê Tiến Dũng — FastAPI web platform.
Run: uvicorn app:app --host 0.0.0.0 --port $PORT
"""
import os
import time
import asyncio
import json
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Body, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

import database as db
import auth
import guard
from task_manager import manager
from tools import TOOL_META

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="PhantomCustom", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)

import backup
import telegram_bot
from backup import start as backup_start

backup_start()   # khôi phục DB từ GitHub backup (container mới) + bật backup tự động
db.init_db()
db.seed_admin()
telegram_bot.start()   # bot Telegram: lệnh admin từ xa + thông báo user mới


# ---------------- lớp bảo vệ tải / ổn định ----------------
class GuardMiddleware(BaseHTTPMiddleware):
    """Chặn body quá lớn, rate-limit theo IP, thêm header cache cho static."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 1) chặn body quá lớn (đọc header trước khi parse)
        try:
            clen = int(request.headers.get("content-length") or 0)
        except Exception:
            clen = 0
        if clen > guard.MAX_BODY_BYTES:
            return JSONResponse({"detail": "Dữ liệu gửi lên quá lớn (tối đa 4MB)"}, status_code=413)

        # 2) rate limit
        limit, window = guard.rule_for(path)
        if limit:
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                  or (request.client.host if request.client else "?"))
            if not guard.limiter.allow(f"{ip}|{path.split('/')[2] if len(path.split('/')) > 2 else path}", limit, window):
                return JSONResponse(
                    {"detail": "Bạn thao tác quá nhanh, vui lòng thử lại sau vài giây"},
                    status_code=429,
                )

        response = await call_next(request)

        # 3) cache: asset có ?v=... thì cache dài, còn HTML thì KHÔNG cache
        if path.startswith("/static/"):
            if request.query_params.get("v"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        elif path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


app.add_middleware(GuardMiddleware)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Không bao giờ để lộ stack trace / sập trắng trang."""
    print("[error]", request.url.path, type(exc).__name__, exc)
    return JSONResponse({"detail": "Máy chủ gặp lỗi tạm thời, vui lòng thử lại"}, status_code=500)


@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")

# resume persisted tasks on startup
@app.on_event("startup")
async def _startup():
    n = manager.resume_persisted()
    print(f"[startup] resumed {n} tasks")

app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


# ---------------- auth ----------------
class Credentials(BaseModel):
    username: str
    password: str


@app.post("/api/register")
def register(c: Credentials):
    if len(c.username) < 3 or len(c.password) < 4:
        raise HTTPException(400, "Tên đăng nhập >=3 ký tự, mật khẩu >=4 ký tự")
    uid = db.create_user(c.username.strip(), c.password)
    if not uid:
        raise HTTPException(400, "Tên đăng nhập đã tồn tại")
    backup.schedule_soon()   # user mới phải có trên backup càng sớm càng tốt
    token = db.create_session(uid)
    user = db.get_user(uid)
    telegram_bot.notify(f"🆕 <b>Đăng ký mới!</b>\nUser: <b>{user['username']}</b> (#{uid})\nThời gian: {time.strftime('%d/%m/%Y %H:%M')}\nTổng số user: {len(db.list_users())}")
    return {"token": token, "user": auth.public_user(user)}


@app.post("/api/login")
def login(c: Credentials):
    user = db.get_user_by_name(c.username.strip())
    if not user or not db.verify_password(c.password, user["password_hash"]):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    if user.get("banned"):
        raise HTTPException(403, "Tài khoản đã bị khoá")
    db.touch_login(user["id"])
    token = db.create_session(user["id"])
    user = db.get_user(user["id"])
    return {"token": token, "user": auth.public_user(user)}


@app.post("/api/logout")
def logout(user=Depends(auth.current_user)):
    db.delete_session(user["_token"])
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    return auth.public_user(user)


# ---------------- tools ----------------
@app.get("/api/tools")
def tools():
    return TOOL_META


@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(BASE, "static", "favicon.svg"))


# ---------------- facebook info (uid + box list) ----------------
class FbInfoIn(BaseModel):
    cookie: str


@app.post("/api/fb/info")
async def fb_info(body: FbInfoIn, user=Depends(auth.current_user)):
    """Lấy UID, tên và danh sách box từ cookie Facebook."""
    from tools import fb_info as fbi
    cookie = (body.cookie or "").strip()
    if len(cookie) > 20000:
        raise HTTPException(status_code=413, detail="Cookie quá dài")
    try:
        return await asyncio.to_thread(fbi.get_info, cookie)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Không lấy được thông tin: {e}")


# ---------------- zalo: tự lấy box từ IMEI + cookie ----------------
class ZaloGroupsIn(BaseModel):
    imei: str = ""
    cookies: str = ""


_zalo_scan_sem = asyncio.Semaphore(3)   # tránh mở quá nhiều phiên Zalo cùng lúc


@app.post("/api/zalo/groups")
async def zalo_groups(body: ZaloGroupsIn, user=Depends(auth.current_user)):
    """Đăng nhập bằng IMEI + session cookie và trả về toàn bộ nhóm đang tham gia."""
    from tools.zalo_session import (
        login as zalo_login,
        auto_groups_detail,
        account_info,
        ZaloSessionError,
    )

    imei = (body.imei or "").strip()
    cookies = (body.cookies or "").strip()
    if not imei and not cookies:
        raise HTTPException(status_code=400, detail="Nhập IMEI + cookie Zalo trước đã.")
    if len(cookies) > 40000:
        raise HTTPException(status_code=413, detail="Cookie quá dài")

    def _work():
        bot = zalo_login(imei, cookies)
        boxes = auto_groups_detail(bot)   # [{id, name}] — UID kèm tên nhóm như mess
        try:
            info = account_info(bot) or {}
        except Exception:
            info = {}
        return {
            "boxes": boxes,
            "groups": [b["id"] for b in boxes],   # giữ tương thích bản cũ
            "name": info.get("name") or "",
            "uid": info.get("uid") or "",
            "phone": info.get("phone") or "",
        }

    async with _zalo_scan_sem:
        try:
            res = await asyncio.to_thread(_work)
        except ZaloSessionError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Không đọc được nhóm: {e}")

    return {"ok": True, "count": len(res["boxes"]), **res}


# ---------------- checker: live/die hàng loạt ----------------
class CheckIn(BaseModel):
    kind: str
    data: str
    cookie: str = ""


_check_sem = asyncio.Semaphore(4)   # tối đa 4 lượt check nặng cùng lúc


@app.post("/api/check")
async def check_accounts(body: CheckIn, user=Depends(auth.current_user)):
    """Check live/die hàng loạt: discord | fb_cookie | fb_link | zalo.

    Chạy trong threadpool + giới hạn song song để không bao giờ làm nghẽn server.
    """
    from tools import checker
    kind = (body.kind or "").lower()
    if kind not in ("discord", "fb_cookie", "fb_link", "zalo"):
        raise HTTPException(status_code=400, detail="Loại check không hỗ trợ: " + kind)

    data = body.data or ""
    lines = [x for x in data.replace("\r", "").split("\n") if x.strip()]
    cap = guard.MAX_CHECK_LINES_ZALO if kind == "zalo" else guard.MAX_CHECK_LINES
    truncated = 0
    if len(lines) > cap:
        truncated = len(lines) - cap
        lines = lines[:cap]
        data = "\n".join(lines)

    try:
        async with _check_sem:
            res = await asyncio.to_thread(checker.run_check, kind, data, (body.cookie or "").strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi khi check: {e}")

    if truncated:
        res["truncated"] = truncated
        res["note"] = f"Chỉ check {cap} acc đầu tiên, còn {truncated} acc chưa xử lý (chia nhỏ file để check tiếp)"
    return res


# ---------------- tasks ----------------
class TaskIn(BaseModel):
    tool: str
    name: str
    config: dict


@app.get("/api/tasks")
def list_tasks(user=Depends(auth.current_user)):
    return manager.list_for_user(user["id"])


@app.post("/api/tasks")
def create_task(t: TaskIn, user=Depends(auth.current_user)):
    if not auth.has_access(user):
        raise HTTPException(403, "Chưa thuê — vui lòng liên hệ Zalo 0969411158")
    if t.tool not in TOOL_META:
        raise HTTPException(400, "Tool không hợp lệ")
    rt = manager.create(user["id"], t.tool, t.name or TOOL_META[t.tool]["name"], t.config)
    return rt.to_dict(with_logs=True)


@app.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str, user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    manager.stop(task_id)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str, user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    return {"ok": manager.pause(task_id)}


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str, user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    return {"ok": manager.resume(task_id)}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    manager.delete(task_id)
    return {"ok": True}


@app.put("/api/tasks/{task_id}/config")
def update_config(task_id: str, config: dict = Body(...), user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    manager.update_config(task_id, config)
    return {"ok": True}


@app.get("/api/tasks/{task_id}/logs")
def task_logs(task_id: str, user=Depends(auth.current_user)):
    rt = manager.get(task_id)
    if not rt or (rt.user_id != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Không tìm thấy task")
    return {"logs": rt.logs[-100:], "status": rt.status, "uptime": int(rt.uptime())}


# ---------------- notifications (chỉ admin xem được — hành động admin đi qua Telegram) ----------------
@app.get("/api/notifications")
def notifications(user=Depends(auth.current_user)):
    auth.require_admin(user)
    return db.list_notifications()


# ---------------- admin ----------------
@app.get("/api/admin/users")
def admin_users(user=Depends(auth.current_user)):
    auth.require_admin(user)
    users = db.list_users()
    out = []
    for u in users:
        d = auth.public_user(u)
        d["task_count"] = len([t for t in manager.list_for_user(u["id"])])
        out.append(d)
    return out


@app.get("/api/admin/tasks")
def admin_tasks(user=Depends(auth.current_user)):
    auth.require_admin(user)
    return manager.list_all()


@app.post("/api/admin/tasks/{task_id}/stop")
def admin_stop(task_id: str, user=Depends(auth.current_user)):
    auth.require_admin(user)
    t = manager.get(task_id)
    ok = manager.stop(task_id)
    if ok and t:
        owner = db.get_user(t.get("user_id") or 0)
        telegram_bot.notify(
            f"⏹ <b>Admin đã dừng task</b> từ xa trên web\n"
            f"Task: {task_id} ({t.get('tool', '')}) — chủ: {owner['username'] if owner else '?'}")
    return {"ok": ok}


@app.delete("/api/admin/tasks/{task_id}")
def admin_delete(task_id: str, user=Depends(auth.current_user)):
    auth.require_admin(user)
    t = manager.get(task_id)
    ok = manager.delete(task_id)
    if ok and t:
        owner = db.get_user(t.get("user_id") or 0)
        telegram_bot.notify(
            f"🗑 <b>Admin đã xoá task</b> trên web\n"
            f"Task: {task_id} ({t.get('tool', '')}) — chủ: {owner['username'] if owner else '?'}")
    return {"ok": ok}


class GrantIn(BaseModel):
    duration: str  # week | month | year | forever | revoke


@app.post("/api/admin/users/{uid}/grant")
def admin_grant(uid: int, g: GrantIn, user=Depends(auth.current_user)):
    auth.require_admin(user)
    target = db.get_user(uid)
    if not target:
        raise HTTPException(404, "Không tìm thấy user")
    now = time.time()
    table = {"week": 7, "month": 30, "year": 365}
    if g.duration == "forever":
        until, label = 4102444800, "Vĩnh viễn"
    elif g.duration == "revoke":
        until, label = 0, "none"
    elif g.duration in table:
        until = now + table[g.duration] * 86400
        label = {"week": "1 tuần", "month": "1 tháng", "year": "1 năm"}[g.duration]
    else:
        raise HTTPException(400, "duration không hợp lệ")
    db.update_user(uid, access_until=until, access_label=label)
    backup.schedule_soon()
    telegram_bot.notify(f"✅ <b>Admin đã cấp quyền {label}</b> cho {target['username']} (#{uid}) qua web")
    return {"ok": True, "access_until": until, "access_label": label}


@app.post("/api/admin/users/{uid}/ban")
def admin_ban(uid: int, user=Depends(auth.current_user)):
    auth.require_admin(user)
    target = db.get_user(uid)
    if not target:
        raise HTTPException(404, "Không tìm thấy user")
    db.update_user(uid, banned=0 if target.get("banned") else 1)
    if not target.get("banned"):
        manager.stop_all_user(uid)
        telegram_bot.notify(
            f"🚫 <b>Admin đã BAN</b> {target['username']} (#{uid}) qua web — toàn bộ task của họ đã dừng")
    elif target.get("banned"):
        telegram_bot.notify(f"🕊 <b>Admin đã bỏ ban</b> {target['username']} (#{uid}) qua web")
    return {"ok": True, "banned": not target.get("banned")}


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: int, user=Depends(auth.current_user)):
    """Xoá vĩnh viễn user + phiên đăng nhập + toàn bộ task của user."""
    auth.require_admin(user)
    if uid == user["id"]:
        raise HTTPException(400, "Không thể xoá tài khoản admin đang đăng nhập")
    target = db.get_user(uid)
    if not target:
        raise HTTPException(404, "Không tìm thấy user")
    manager.delete_all_user(uid)
    ok = db.delete_user(uid)
    if ok:
        backup.schedule_soon()
        telegram_bot.notify(f"🗑 <b>Admin đã xoá user</b> {target['username']} (#{uid}) qua web — kèm toàn bộ task của họ")
    return {"ok": ok}


# ---------------- thông báo giữa màn hình (announcement) ----------------
class AnnIn(BaseModel):
    text: str


@app.get("/api/announcement")
def announcement_public():
    """Công khai — mọi khách đều đọc được thông báo hiện giữa màn hình."""
    return db.get_announcement()


@app.post("/api/admin/announcement")
def announcement_set(a: AnnIn, user=Depends(auth.current_user)):
    auth.require_admin(user)
    text = (a.text or "").strip()
    if not text:
        raise HTTPException(400, "Nội dung thông báo đang trống")
    if len(text) > 3000:
        raise HTTPException(413, "Nội dung quá dài (tối đa 3000 ký tự)")
    row = db.set_announcement(text)
    backup.schedule_soon()
    telegram_bot.notify(f"📢 <b>Admin đã đăng thông báo</b> giữa màn hình web:\n{text[:500]}")
    return row


@app.delete("/api/admin/announcement")
def announcement_clear(user=Depends(auth.current_user)):
    auth.require_admin(user)
    db.clear_announcement()
    backup.schedule_soon()
    telegram_bot.notify("🗑 <b>Admin đã gỡ thông báo</b> khỏi web")
    return {"ok": True}


# ---------------- websocket realtime ----------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    sess = db.get_session(token)
    if not sess:
        await websocket.close()
        return
    user = db.get_user(sess["user_id"])
    if not user:
        await websocket.close()
        return
    # giới hạn số kết nối realtime để không bao giờ cạn tài nguyên
    if not guard.ws_acquire(user["id"]):
        try:
            await websocket.send_text(json.dumps({"type": "error", "detail": "Quá nhiều kết nối realtime"}))
        except Exception:
            pass
        await websocket.close()
        return
    try:
        while True:
            if user["is_admin"]:
                tasks = manager.list_all()
            else:
                tasks = manager.list_for_user(user["id"])
            # attach live uptime + logs
            enriched = []
            for t in tasks:
                rt = manager.get(t["id"])
                if rt:
                    t["uptime"] = int(rt.uptime())
                    t["logs"] = rt.logs[-15:]
                enriched.append(t)
            await websocket.send_text(json.dumps({
                "type": "tasks",
                "tasks": enriched,
                "server_time": time.time(),
            }, ensure_ascii=False))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception:
        return
    finally:
        guard.ws_release(user["id"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

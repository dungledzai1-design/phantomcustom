"""PhantomCustom by Lê Tiến Dũng — FastAPI web platform.
Run: uvicorn app:app --host 0.0.0.0 --port $PORT
"""
import os
import time
import asyncio
import json
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import auth
from task_manager import manager
from tools import TOOL_META

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="PhantomCustom")

db.init_db()
db.seed_admin()

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
    token = db.create_session(uid)
    user = db.get_user(uid)
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


# ---------------- notifications ----------------
@app.get("/api/notifications")
def notifications(user=Depends(auth.current_user)):
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
    return {"ok": manager.stop(task_id)}


@app.delete("/api/admin/tasks/{task_id}")
def admin_delete(task_id: str, user=Depends(auth.current_user)):
    auth.require_admin(user)
    return {"ok": manager.delete(task_id)}


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
    db.add_notification(f"Admin đã cấp quyền {label} cho {target['username']}", "success")
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
    return {"ok": True, "banned": not target.get("banned")}


class BroadcastIn(BaseModel):
    message: str
    level: str = "info"


@app.post("/api/admin/broadcast")
def admin_broadcast(b: BroadcastIn, user=Depends(auth.current_user)):
    auth.require_admin(user)
    db.add_notification(b.message, b.level)
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
                "notifications": db.list_notifications(10),
                "server_time": time.time(),
            }, ensure_ascii=False))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception:
        return


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

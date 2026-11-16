"""Backup / restore SQLite DB qua GitHub private repo.

Render free plan không có disk — mỗi lần deploy/restart là data/phantom.db bị
xoá sạch (user đăng ký, task treo biến mất). Module này:
  - Khôi phục DB từ repo backup khi container mới khởi động (DB local chưa có).
  - Tự push DB lên repo mỗi INTERVAL giây nếu nội dung thay đổi + khi process tắt.

Env bắt buộc (đặt trong Render → Environment):
  GH_BACKUP_REPO  = "owner/repo"   (repo private, branch main)
  GH_BACKUP_TOKEN = GitHub token có quyền repo
"""
import atexit
import base64
import hashlib
import os
import sqlite3
import tempfile
import threading
import time

import requests

import database as db

INTERVAL = 180           # backup mỗi 3 phút nếu DB đổi
MAX_SIZE = 80 * 1024 * 1024   # contents API giới hạn ~100MB, giữ biên an toàn
PATH = "phantom.db"

_last_hash = None


def _env():
    return (os.environ.get("GH_BACKUP_REPO", "").strip(),
            os.environ.get("GH_BACKUP_TOKEN", "").strip())


def _api(method, url, token, **kwargs):
    return requests.request(method, url, timeout=60,
                            headers={"Authorization": f"Bearer {token}",
                                     "Accept": "application/vnd.github+json"},
                            **kwargs)


def _snapshot():
    """Copy DB ra file tạm bằng sqlite backup API — nhất quán kể cả khi đang ghi."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    try:
        out = sqlite3.connect(tmp, timeout=30)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()
    return tmp


def remote_sha(repo, token):
    r = _api("GET", f"https://api.github.com/repos/{repo}/contents/{PATH}", token,
             params={"ref": "main"})
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def restore(repo, token):
    """Tải DB từ repo nếu DB local chưa tồn tại (container mới của Render)."""
    if os.path.exists(db.DB_PATH) and os.path.getsize(db.DB_PATH) > 0:
        return False
    r = _api("GET", f"https://api.github.com/repos/{repo}/contents/{PATH}", token,
             params={"ref": "main"})
    if r.status_code != 200:
        return False
    raw = base64.b64decode(r.json().get("content") or "")
    if not raw:
        return False
    os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
    tmp = db.DB_PATH + ".restore"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, db.DB_PATH)
    return True


def backup_once(repo=None, token=None):
    """Push DB lên repo nếu nội dung đổi. Trả về True nếu đã push."""
    global _last_hash
    repo, token = repo or _env()[0], token or _env()[1]
    if not (repo and token) or not os.path.exists(db.DB_PATH):
        return False
    if os.path.getsize(db.DB_PATH) > MAX_SIZE:
        return False
    snap = _snapshot()
    try:
        with open(snap, "rb") as f:
            raw = f.read()
        h = hashlib.sha256(raw).hexdigest()
        if h == _last_hash:
            return False
        payload = {
            "message": f"auto backup {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(raw).decode(),
            "branch": "main",
        }
        sha = remote_sha(repo, token)
        if sha:
            payload["sha"] = sha
        r = _api("PUT", f"https://api.github.com/repos/{repo}/contents/{PATH}", token, json=payload)
        if r.status_code in (200, 201):
            _last_hash = h
            return True
        return False
    finally:
        try:
            os.unlink(snap)
        except Exception:
            pass


def _loop():
    while True:
        time.sleep(INTERVAL)
        try:
            backup_once()
        except Exception:
            pass


def start():
    """Khôi phục DB (nếu container mới) + bật luồng backup. Trả về True nếu bật."""
    repo, token = _env()
    if not (repo and token):
        return False
    try:
        if restore(repo, token):
            print("[backup] đã khôi phục DB từ GitHub backup ✅")
        else:
            print("[backup] không có bản backup cũ (hoặc DB local đã có) — dùng DB hiện tại")
    except Exception as e:
        print("[backup] restore lỗi:", e)

    def _on_exit():
        try:
            backup_once(repo, token)
        except Exception:
            pass

    atexit.register(_on_exit)
    threading.Thread(target=_loop, daemon=True).start()
    print(f"[backup] bật tự động backup mỗi {INTERVAL}s → {repo}")
    return True

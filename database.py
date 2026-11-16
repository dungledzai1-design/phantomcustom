"""SQLite persistence layer for PhantomCustom.
Lightweight, no ORM, WAL mode for concurrency. Safe for Render free tier.
"""
import sqlite3
import os
import time
import json
import threading
import hashlib
import secrets

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "phantom.db")
_lock = threading.RLock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=8000")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA wal_autocheckpoint=400")
    return c


def _retry(fn, attempts=4, delay=0.08):
    """Chạy 1 thao tác DB, tự thử lại khi SQLite bị khoá (nhiều luồng cùng ghi)."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            last = e
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            time.sleep(delay * (i + 1))
    if last:
        raise last


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                access_until REAL DEFAULT 0,
                access_label TEXT DEFAULT 'none',
                created_at REAL NOT NULL,
                last_login REAL DEFAULT 0,
                banned INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                tool TEXT NOT NULL,
                name TEXT NOT NULL,
                config TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                created_at REAL NOT NULL,
                started_at REAL NOT NULL,
                stopped_at REAL DEFAULT 0,
                sent_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT '',
                log TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                level TEXT DEFAULT 'info',
                created_at REAL NOT NULL
            );
            """
        )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
        return secrets.compare_digest(dk.hex(), h)
    except Exception:
        return False


# ---------------- Users ----------------
def create_user(username, password, is_admin=0, access_until=0, access_label="none"):
    with _lock, _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO users (username,password_hash,is_admin,access_until,access_label,created_at) VALUES (?,?,?,?,?,?)",
                (username, hash_password(password), is_admin, access_until, access_label, time.time()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_user_by_name(username):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(r) if r else None


def get_user(uid):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None


def list_users():
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def update_user(uid, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE users SET {cols} WHERE id=?", (*fields.values(), uid))


def touch_login(uid):
    update_user(uid, last_login=time.time())


def delete_user(uid):
    """Xoá vĩnh viễn user + toàn bộ phiên đăng nhập + task của user."""
    with _lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM tasks WHERE user_id=?", (uid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))
    return get_user(uid) is None


# ---------------- Sessions ----------------
def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO sessions (token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
            (token, user_id, now, now + 86400 * 30),
        )
    return token


def get_session(token):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        if not r:
            return None
        if r["expires_at"] < time.time():
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            return None
        return dict(r)


def delete_session(token):
    with _lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------------- Tasks ----------------
def save_task(task):
    with _lock, _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO tasks
               (id,user_id,tool,name,config,status,created_at,started_at,stopped_at,sent_count,last_error,log)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task["id"], task["user_id"], task["tool"], task["name"],
                json.dumps(task.get("config", {}), ensure_ascii=False),
                task.get("status", "running"), task.get("created_at", time.time()),
                task.get("started_at", time.time()), task.get("stopped_at", 0),
                task.get("sent_count", 0), task.get("last_error", ""),
                task.get("log", ""),
            ),
        )


def update_task(task_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))


def get_task(task_id):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _task_row(r) if r else None


def list_tasks(user_id=None):
    with _lock, _conn() as c:
        if user_id is None:
            rows = c.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        else:
            rows = c.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [_task_row(r) for r in rows]


def delete_task(task_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))


def _task_row(r):
    d = dict(r)
    try:
        d["config"] = json.loads(d.get("config") or "{}")
    except Exception:
        d["config"] = {}
    return d


# ---------------- Notifications ----------------
def add_notification(message, level="info"):
    with _lock, _conn() as c:
        c.execute("INSERT INTO notifications (message,level,created_at) VALUES (?,?,?)", (message, level, time.time()))


def list_notifications(limit=30):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def seed_admin():
    u = get_user_by_name("dungledev")
    if not u:
        create_user("dungledev", "dunglengaongo", is_admin=1, access_until=4102444800, access_label="forever")
        print("[seed] admin dungledev created")
    else:
        update_user(u["id"], is_admin=1, access_until=4102444800, access_label="forever")

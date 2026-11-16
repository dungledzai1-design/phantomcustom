"""Authentication helpers for PhantomCustom."""
import time
import database as db
from fastapi import Header, HTTPException


def current_user(authorization: str = Header(default="")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    token = authorization.replace("Bearer ", "").strip()
    sess = db.get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập hết hạn")
    user = db.get_user(sess["user_id"])
    if not user or user.get("banned"):
        raise HTTPException(status_code=401, detail="Tài khoản bị khoá")
    user["_token"] = token
    return user


def require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Chỉ admin")
    return user


def has_access(user):
    if user.get("is_admin"):
        return True
    return float(user.get("access_until") or 0) > time.time()


def access_label(user):
    if user.get("is_admin"):
        return "Admin vĩnh viễn"
    if float(user.get("access_until") or 0) > time.time():
        return user.get("access_label") or "Đã cấp quyền"
    return "Chưa thuê"


def public_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "access": has_access(user),
        "access_label": access_label(user),
        "access_until": user.get("access_until", 0),
        "created_at": user.get("created_at", 0),
        "last_login": user.get("last_login", 0),
        "banned": bool(user.get("banned", 0)),
    }

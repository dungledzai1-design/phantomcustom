"""Zalo session helper — chỉ cần IMEI + cookie, KHÔNG cần phone/password/api_key.

zlapi 1.0.2/1.0.3 mặc định bắt buộc phone+password khi auto_login=True, kể cả khi
đã có cookie. Module này khởi tạo bot với auto_login=False, nạp cookie trực tiếp
vào state rồi gọi luồng login bằng cookie (getLoginInfo?imei=...) nên chạy được
chỉ với IMEI + session cookie.

Ngoài ra cung cấp auto_groups() để tự đọc toàn bộ nhóm đang tham gia — người
dùng không cần nhập link box.
"""
import json
import re

try:
    from zlapi import ZaloAPI
    ZLAPI_OK = True
except Exception:  # pragma: no cover
    ZLAPI_OK = False


class ZaloSessionError(Exception):
    pass


def parse_cookie(raw):
    """Chuẩn hoá cookie về dict. Hỗ trợ JSON (kể cả dán nguyên file .txt có dòng
    tiêu đề), JSON lồng, và chuỗi 'a=b; c=d'."""
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return {}
        data = None
        # 1) Toàn bộ chuỗi là JSON
        try:
            data = json.loads(text)
        except Exception:
            pass
        # 2) JSON nằm giữa các dòng tiêu đề của file .txt (vd '=== ZALO COOKIE ===')
        #    → tách khối { ... } đầu tiên, tránh nhầm dấu '=' trong tiêu đề thành cookie
        if not isinstance(data, dict):
            m = re.search(r"\{[^{}]*\}", text, re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None
        # 3) Chuỗi cookie kiểu 'a=b; c=d'
        if not isinstance(data, dict):
            out = {}
            for part in re.split(r"[;\n]+", text):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k.strip()] = v.strip()
            data = out
    if not isinstance(data, dict):
        return {}
    # JSON export dạng {"imei": "...", "cookies": {...}}
    for key in ("cookies", "cookie", "session", "session_cookies"):
        inner = data.get(key)
        if isinstance(inner, dict) and inner:
            return inner
        if isinstance(inner, str) and inner.strip().startswith("{"):
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict) and parsed:
                    return parsed
            except Exception:
                pass
    meta = {"imei", "phone", "password", "name", "uid", "userId", "savedAt", "createdAt"}
    clean = {k: v for k, v in data.items() if k not in meta}
    return clean or data


def parse_imei(raw_cookie, raw_imei=""):
    """Lấy IMEI từ ô nhập, nếu trống thì thử đọc trong JSON cookie hoặc dòng
    'IMEI: xxx' trong file .txt (không phân biệt hoa/thường)."""
    imei = str(raw_imei or "").strip()
    if imei:
        return imei
    text = str(raw_cookie or "")
    m = re.search(r'"imei"\s*:\s*"([^"]+)"', text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bimei\s*[=:]\s*([A-Za-z0-9_-]{8,})", text, re.I)
    return m.group(1).strip() if m else ""


def _new_bot():
    """Tạo ZaloAPI ở chế độ không auto-login (tránh lỗi 'Phone and password not set')."""
    try:
        return ZaloAPI(auto_login=False)
    except TypeError:
        return ZaloAPI(None, None, None, None, auto_login=False)


def login(imei, raw_cookie):
    """Đăng nhập Zalo chỉ bằng IMEI + cookie. Trả về bot đã sẵn sàng."""
    if not ZLAPI_OK:
        raise ZaloSessionError("Thiếu thư viện zlapi trên server.")
    imei = parse_imei(raw_cookie, imei)
    ck = parse_cookie(raw_cookie)
    if not imei:
        raise ZaloSessionError("Thiếu IMEI — dán IMEI hoặc dùng file cookie có kèm imei.")
    if not ck:
        raise ZaloSessionError("Cookie không hợp lệ — cần JSON session cookie của Zalo.")

    bot = _new_bot()
    try:
        bot.setSession(ck)
    except Exception as e:
        raise ZaloSessionError(f"Không nạp được cookie: {e}")

    state = getattr(bot, "_state", None)
    if state is None:
        raise ZaloSessionError("Không khởi tạo được state zlapi.")
    try:
        state.login(None, None, imei)
    except TypeError:
        state.login(None, None, imei, None)
    except Exception as e:
        msg = str(e)
        if "NoneType" in msg or "not subscriptable" in msg:
            raise ZaloSessionError(
                "Zalo từ chối đăng nhập bằng cookie này — cookie sai định dạng, "
                "thiếu key hoặc đã bị đăng xuất. Hãy lấy lại cookie mới (file .txt "
                "đầy đủ IMEI + COOKIE JSON dán thẳng vào ô Cookie là được)."
            )
        raise ZaloSessionError(f"Cookie hết hạn hoặc sai IMEI: {msg}")

    try:
        logged = bot.isLoggedIn()
    except Exception:
        logged = bool(getattr(state, "_loggedin", False))
    if not logged:
        raise ZaloSessionError("Cookie Zalo đã hết hạn — lấy cookie mới rồi thử lại.")

    uid = getattr(state, "user_id", None) or getattr(state, "cloud_id", None)
    try:
        bot._imei = imei
    except Exception:
        pass
    if uid:
        try:
            bot.user_id = uid
        except Exception:
            pass
        # 1.0.2 dùng thuộc tính bot.uid, 1.0.3 dùng method bot.uid()
        if not callable(getattr(type(bot), "uid", None)):
            try:
                bot.uid = uid
            except Exception:
                pass
    try:
        bot.cloud_id = getattr(state, "cloud_id", None) or uid
    except Exception:
        pass
    return bot


def account_info(bot):
    """Trả về dict {name, uid, phone} — không raise."""
    out = {"name": "", "uid": "", "phone": ""}
    try:
        info = bot.fetchAccountInfo()
        profile = getattr(info, "profile", None) or {}
        if hasattr(profile, "get"):
            out["name"] = profile.get("displayName") or profile.get("zaloName") or profile.get("username") or ""
            out["uid"] = str(profile.get("userId") or "")
            out["phone"] = str(profile.get("phoneNumber") or "")
    except Exception:
        pass
    return out


def auto_groups(bot, limit=200):
    """Tự đọc toàn bộ group ID người dùng đang tham gia (không cần nhập link box).

    zlapi trả về Group(version=..., gridVerMap={gid: lastUpdate}) — lấy key của
    gridVerMap chính là group ID thật.
    """
    groups = []

    def _collect(obj, depth=0):
        if depth > 3 or obj is None:
            return
        if isinstance(obj, dict):
            grid = obj.get("gridVerMap") or obj.get("gridInfoMap")
            if isinstance(grid, dict):
                for gid in grid.keys():
                    gid = str(gid).strip()
                    if gid.isdigit() and gid not in groups:
                        groups.append(gid)
                return
            for key in ("groups", "data", "items", "list"):
                if key in obj:
                    _collect(obj[key], depth + 1)
                    if groups:
                        return
            # dict thuần {gid: ...}
            for gid in obj.keys():
                if str(gid).isdigit() and str(gid) not in groups:
                    groups.append(str(gid))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _collect(item, depth + 1)
                if groups:
                    return
        else:
            # Group object (DefaultMunch)
            for attr in ("gridVerMap", "gridInfoMap", "groups", "data"):
                if hasattr(obj, attr):
                    _collect(getattr(obj, attr), depth + 1)
                    if groups:
                        return

    try:
        _collect(bot.fetchAllGroups())
    except Exception:
        return groups
    return groups[:limit]

"""Bộ kiểm tra live/die tài khoản (Discord token, Facebook cookie/link, Zalo IMEI+cookie).

Tất cả hàm đều nhận danh sách thô (mỗi dòng 1 acc) và trả về list kết quả:
    {"input": <dòng gốc>, "status": "live"|"die"|"unknown", "name": ..., "id": ...,
     "note": ..., "type": ...}
Chỉ đọc thông tin, KHÔNG gửi tin nhắn, KHÔNG làm gì ảnh hưởng tới acc.
"""
import html as html_lib
import json
import re
import threading
import time

import requests

# ------------------------------------------------------------------ helpers
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _lines(raw):
    """Tách input thô thành list dòng có ý nghĩa (bỏ header/comment/rỗng)."""
    out = []
    for ln in str(raw or "").replace("\r", "").split("\n"):
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("===") or low.startswith("---") or low.startswith("#"):
            continue
        if low.startswith("tên:") or low.startswith("ten:") or low.startswith("thời gian"):
            continue
        if low.startswith("lấy bởi") or low.startswith("lay boi"):
            continue
        out.append(s)
    return out


# ------------------------------------------------------------------ discord
def check_discord_token(token):
    token = (token or "").strip().strip('"').strip("'")
    if not token:
        return {"input": token, "status": "die", "name": "", "id": "",
                "note": "Token rỗng", "type": "discord"}
    if token.lower().startswith("mfa."):
        token = token[4:]
    h = {"Authorization": token, "User-Agent": UA,
         "Content-Type": "application/json", "Accept": "*/*"}
    for attempt in range(2):
        try:
            r = requests.get("https://discord.com/api/v9/users/@me",
                             headers=h, timeout=20)
        except Exception as e:
            if attempt:
                return {"input": token, "status": "unknown", "name": "", "id": "",
                        "note": f"Lỗi mạng: {e}", "type": "discord"}
            time.sleep(1.2)
            continue
        if r.status_code == 200:
            d = r.json()
            name = d.get("global_name") or d.get("username") or ""
            extra = []
            if d.get("email"):
                extra.append(d["email"])
            if d.get("phone"):
                extra.append(d["phone"])
            if d.get("verified") is False:
                extra.append("chưa verify")
            return {"input": token, "status": "live", "name": name,
                    "id": str(d.get("id", "")),
                    "note": " · ".join(extra) or d.get("username", ""),
                    "type": "discord"}
        if r.status_code == 401:
            return {"input": token, "status": "die", "name": "", "id": "",
                    "note": "Token sai / đã bị đổi mật khẩu", "type": "discord"}
        if r.status_code == 403:
            return {"input": token, "status": "die", "name": "", "id": "",
                    "note": "Token bị khoá (403)", "type": "discord"}
        if r.status_code == 429:
            time.sleep(2.5)
            continue
        return {"input": token, "status": "unknown", "name": "", "id": "",
                "note": f"HTTP {r.status_code}", "type": "discord"}
    return {"input": token, "status": "unknown", "name": "", "id": "",
            "note": "Bị rate-limit, thử lại sau", "type": "discord"}


def check_discord(raw):
    toks = _lines(raw)
    return [check_discord_token(t) for t in toks]


# ------------------------------------------------------------------ facebook
def _fb_headers(cookie=""):
    h = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }
    if cookie:
        h["Cookie"] = cookie
    return h


def _fb_session(cookie=""):
    s = requests.Session()
    s.headers.update(_fb_headers(cookie))
    return s


def _title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _is_login_wall(html, final_url):
    if "/login" in (final_url or ""):
        return True
    t = (html or "")[:6000].lower()
    return ('name="email"' in t and 'name="pass"' in t)


def check_fb_cookie(cookie):
    """Cookie dạng 'c_user=...; xs=...' -> live/die + tên."""
    cookie = (cookie or "").strip()
    m = re.search(r"(?:^|;\s*)c_user=(\d+)", cookie)
    if not m:
        return {"input": cookie, "status": "die", "name": "", "id": "",
                "note": "Thiếu c_user trong cookie", "type": "fb_cookie"}
    uid = m.group(1)
    s = _fb_session(cookie)
    try:
        r = s.get(f"https://www.facebook.com/profile.php?id={uid}",
                  timeout=25, allow_redirects=True)
        html = r.text
        if _is_login_wall(html, r.url):
            return {"input": cookie, "status": "die", "name": "", "id": uid,
                    "note": "Cookie chết (bị đẩy ra trang đăng nhập)", "type": "fb_cookie"}
        og = re.search(r'property="og:title" content="([^"]*)"', html)
        name = og.group(1) if og else ""
        name = html_lib.unescape(name)
        name = re.sub(r"[\ufe0e\ufe0f\u200d\u200b\u2060\u00ad]", "", name).strip()
        if not name or name in ("Facebook", "Đăng nhập Facebook"):
            name = ""
        if len(html) < 450_000:
            return {"input": cookie, "status": "die", "name": "", "id": uid,
                    "note": "Cookie chết (FB không trả profile)", "type": "fb_cookie"}
        if name:
            return {"input": cookie, "status": "live", "name": name, "id": uid,
                    "note": "Cookie còn sống", "type": "fb_cookie"}
        try:
            from . import fb_info as fbi
            nm2 = fbi.get_name(s, uid)
            if nm2:
                return {"input": cookie, "status": "live", "name": nm2, "id": uid,
                        "note": "Cookie còn sống", "type": "fb_cookie"}
        except Exception:
            pass
        return {"input": cookie, "status": "unknown", "name": "", "id": uid,
                "note": "Không đọc được tên (FB chặn tạm thời) — thử lại sau",
                "type": "fb_cookie"}
    except Exception as e:
        return {"input": cookie, "status": "unknown", "name": "", "id": uid,
                "note": f"Lỗi mạng: {e}", "type": "fb_cookie"}


def check_fb_cookies(raw):
    return [check_fb_cookie(c) for c in _lines(raw)]


def _normalize_fb_link(x):
    x = x.strip()
    if not x:
        return ""
    if re.fullmatch(r"\d{6,}", x):
        return f"https://www.facebook.com/profile.php?id={x}"
    if x.startswith("http://") or x.startswith("https://"):
        return x
    if x.startswith("facebook.com") or x.startswith("www.facebook.com") or x.startswith("m.facebook.com"):
        return "https://" + x
    return "https://www.facebook.com/" + x.lstrip("@/ ")


def check_fb_link(link, cookie=""):
    """Check link/profile FB còn tồn tại hay không (dùng cookie nếu có để chính xác hơn)."""
    url = _normalize_fb_link(link)
    if not url:
        return {"input": link, "status": "die", "name": "", "id": "",
                "note": "Link rỗng", "type": "fb_link"}
    s = _fb_session(cookie)
    try:
        r = s.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        return {"input": link, "status": "unknown", "name": "", "id": "",
                "note": f"Lỗi mạng: {e}", "type": "fb_link"}
    html = r.text or ""
    low = html.lower()
    title = _title(html)
    if _is_login_wall(html, r.url):
        if cookie:
            return {"input": link, "status": "die", "name": "", "id": "",
                    "note": "Không tồn tại / đã bị khoá (FB trả trang đăng nhập)",
                    "type": "fb_link"}
        return {"input": link, "status": "unknown", "name": "", "id": "",
                "note": "FB chặn xem ẩn danh — dán cookie ở ô dưới để check chính xác",
                "type": "fb_link"}
    for marker in ("this content isn't available", "nội dung này không",
                   "page not found", "không tìm thấy trang", "content not found",
                   "liên kết bạn theo dõi có thể đã bị hỏng"):
        if marker in low:
            return {"input": link, "status": "die", "name": "", "id": "",
                    "note": "Trang không tồn tại / đã bị xoá", "type": "fb_link"}
    van = re.search(r'"userVanity":"([^"]+)"', html)
    nm = re.search(r'property="og:title" content="([^"]*)"', html)
    name = ""
    if nm:
        name = nm.group(1)
    elif title and title not in ("Facebook", "Đăng nhập Facebook", "Error"):
        name = title
    elif van:
        name = van.group(1)
    name = re.sub(r"[\ufe0e\ufe0f\u200d\u200b\u2060\u00ad]", "", name).strip()
    if name and name not in ("Facebook", "Error"):
        return {"input": link, "status": "live", "name": name, "id": "",
                "note": "Link còn sống", "type": "fb_link"}
    if len(html) > 1_400_000:
        return {"input": link, "status": "live", "name": title or "", "id": "",
                "note": "Trang tồn tại", "type": "fb_link"}
    return {"input": link, "status": "die", "name": "", "id": "",
            "note": "Không tìm thấy trang (link die)", "type": "fb_link"}


def check_fb_links(raw, cookie=""):
    return [check_fb_link(x, cookie) for x in _lines(raw)]


# ------------------------------------------------------------------ zalo
def _parse_zalo_blocks(raw):
    """Hỗ trợ 2 dạng:
    1) Mỗi dòng:  imei|cookie_json   hoặc  imei|cookie_string
    2) File export nhiều acc:  'IMEI: xxx' + '--- COOKIE JSON ---' + {...}
    """
    text = str(raw or "").replace("\r", "")
    blocks = []
    if re.search(r"^\s*IMEI\s*:", text, re.M | re.I):
        for chunk in re.split(r"(?=^\s*IMEI\s*:)", text, flags=re.M | re.I):
            mi = re.search(r"^\s*IMEI\s*:\s*(\S+)", chunk, re.M | re.I)
            if not mi:
                continue
            imei = mi.group(1).strip()
            mj = re.search(r"\{[\s\S]*\}", chunk)
            cookie = mj.group(0) if mj else ""
            if not cookie:
                mc = re.search(r"COOKIE[^\n]*\n(.+)", chunk, re.I)
                cookie = mc.group(1).strip() if mc else ""
            blocks.append((imei, cookie))
        return blocks
    for ln in _lines(text):
        if "|" in ln:
            imei, cookie = ln.split("|", 1)
            blocks.append((imei.strip(), cookie.strip()))
        else:
            blocks.append(("", ln.strip()))
    return blocks


def _zalo_login(imei, cookie):
    from .zalo_session import login as zalo_login  # chỉ cần IMEI + cookie
    return zalo_login(imei, cookie)


def check_zalo(imei, cookie):
    imei = (imei or "").strip()
    if not imei:
        return {"input": f"{imei}|{str(cookie)[:40]}", "status": "die", "name": "", "id": "",
                "note": "Thiếu IMEI", "type": "zalo"}
    box = {}

    def _work():
        try:
            bot = _zalo_login(imei, cookie)
            from .zalo_session import account_info
            info = account_info(bot)
            box["name"] = info.get("name", "")
            box["id"] = info.get("uid", "")
            box["phone"] = info.get("phone", "")
            box["ok"] = True
        except Exception as e:
            box["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(75)
    if t.is_alive():
        return {"input": f"{imei}|...", "status": "unknown", "name": "", "id": imei,
                "note": "Zalo không phản hồi (timeout 75s)", "type": "zalo"}
    if box.get("ok"):
        note = box.get("phone") or "Session còn sống"
        return {"input": f"{imei}|...", "status": "live", "name": box.get("name", ""),
                "id": box.get("id", ""), "note": note, "type": "zalo"}
    err = box.get("err", "Không đăng nhập được")
    low = err.lower()
    die_markers = ("cookie", "login", "session", "401", "403", "invalid", "expired",
                   "không hợp lệ", "unauthor")
    status = "die" if any(k in low for k in die_markers) else "unknown"
    return {"input": f"{imei}|...", "status": status, "name": "", "id": imei,
            "note": err[:160], "type": "zalo"}


def check_zalos(raw):
    out = []
    for imei, cookie in _parse_zalo_blocks(raw):
        out.append(check_zalo(imei, cookie))
    return out


# ------------------------------------------------------------------ entry
def _guarded(items, fn, budget, type_name):
    """Chạy từng acc, dừng khi hết ngân sách thời gian (server không bị treo)."""
    out = []
    start = time.time()
    for i, it in enumerate(items):
        if budget and time.time() - start > budget:
            for rest in items[i:]:
                out.append({"input": str(rest)[:200], "status": "unknown", "name": "",
                            "id": "", "note": "Hết thời gian xử lý — chia nhỏ file để check tiếp",
                            "type": type_name})
            break
        try:
            out.append(fn(it))
        except Exception as e:
            out.append({"input": str(it)[:200], "status": "unknown", "name": "", "id": "",
                        "note": f"Lỗi: {type(e).__name__}", "type": type_name})
    return out


def run_check(kind, data, cookie="", budget=240):
    kind = (kind or "").lower()
    if kind == "discord":
        res = _guarded(_lines(data), check_discord_token, budget, "discord")
    elif kind == "fb_cookie":
        res = _guarded(_lines(data), check_fb_cookie, budget, "fb_cookie")
    elif kind == "fb_link":
        res = _guarded(_lines(data), lambda x: check_fb_link(x, cookie), budget, "fb_link")
    elif kind == "zalo":
        res = _guarded(_parse_zalo_blocks(data),
                       lambda b: check_zalo(b[0], b[1]), budget, "zalo")
    else:
        raise ValueError("Loại check không hỗ trợ: " + kind)
    live = sum(1 for r in res if r["status"] == "live")
    die = sum(1 for r in res if r["status"] == "die")
    unknown = sum(1 for r in res if r["status"] == "unknown")
    return {"results": res, "total": len(res), "live": live, "die": die,
            "unknown": unknown, "kind": kind}

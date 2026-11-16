"""Facebook info helpers: lấy UID, tên và danh sách box (thread) từ cookie.

Không gửi tin nhắn — chỉ đọc thông tin tài khoản & hội thoại.
Chiến lược:
  1. Probe session ngay từ đầu: cookie chết / checkpoint -> báo lỗi rõ ràng, fail fast.
  2. GraphQL thread list (dùng fb_dtsg từ trang chủ, thử nhiều doc_id).
  3. Fallback HTML: m.facebook.com (UA mobile, server-render) + www messages.
"""
import re
import json
import html
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")

# doc_id query MessengerThreadList — FB đổi theo đợt, thử lần lượt từ mới -> cũ
THREAD_DOC_IDS = [
    "1349387578499440",   # trả shape chuẩn viewer.message_threads
    "8950423881581457",
    "6884651387771581",
    "3336396838921549",
]


def _headers(cookie: str, ua: str = UA_DESKTOP) -> dict:
    return {
        "Cookie": cookie,
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def _session(cookie: str) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.8, status_forcelist=[429, 500, 502, 503])
    ad = HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=retry)
    s.mount("http://", ad)
    s.mount("https://", ad)
    s.headers.update(_headers(cookie))
    return s


def get_uid(cookie: str) -> str:
    m = re.search(r"c_user=(\d+)", cookie or "")
    if not m:
        raise ValueError("Cookie không hợp lệ (thiếu c_user)")
    return m.group(1)


def _clean(txt: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", txt or "")
    txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
    return _sanitize(txt)


def _sanitize(txt: str) -> str:
    """Bỏ variation selector / ký tự vô hình, gộp khoảng trắng."""
    txt = txt or ""
    txt = re.sub(r"[\ufe0e\ufe0f\u200d\u200b\u2060\u00ad]", "", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" ,")
    return txt


def get_name(s: requests.Session, uid: str) -> str:
    """Lấy tên hiển thị (og:title) từ trang cá nhân."""
    for url in (f"https://www.facebook.com/profile.php?id={uid}",
                f"https://www.facebook.com/{uid}",
                f"https://mbasic.facebook.com/profile.php?id={uid}"):
        try:
            r = s.get(url, timeout=15)
            if r.status_code != 200:
                continue
            m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', r.text)
            if m:
                name = html.unescape(m.group(1)).split("|")[0].strip()
                if name and name.lower() != "facebook":
                    return name
            m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S)
            if m:
                name = _clean(m.group(1)).split("|")[0].strip()
                if name and "Facebook" not in name:
                    return name
        except Exception:
            continue
    return ""


_DTSG_PATTERNS = [
    r'"DTSGInitialData",\[\],\{"token":"([^"]+)"',
    r'"DTSGInitData",\[\],\{"token":"([^"]+)"',
    r'"DTSGInitialData":\[\]\s*,\s*\{"token":"([^"]+)"',
    r'["\']fb_dtsg["\']\s*:\s*["\']([^"\']{25,})',
    r'name="fb_dtsg"\s+value="([^"]+)"',
    r'"async_get_request_token":"([^"]+)"',
]

_LSD_PATTERNS = [
    r'"LSD",\[\],\{"token":"([^"]+)"',
    r'"LSD":\[\]\s*,\s*\{"token":"([^"]+)"',
    r'["\']lsd["\']\s*:\s*["\']([^"\']{8,})',
]


def _extract(text: str, patterns) -> str:
    for pat in patterns:
        m = re.search(pat, text or "")
        if m:
            return m.group(1)
    return ""


def _probe_session(s: requests.Session, uid: str):
    """GET trang chủ 1 lần: xác định cookie sống/chết + lấy sẵn dtsg/lsd.

    Trả về (status, home_html): status in {"ok", "login", "checkpoint"}.
    """
    try:
        r = s.get("https://www.facebook.com/", timeout=20)
    except Exception:
        return "ok", ""   # lỗi mạng: bỏ qua probe, để bước sau thử tiếp
    final = str(r.url)
    if "checkpoint" in final:
        return "checkpoint", r.text
    if re.search(r"login(_via|\.php|/)?", final.split("//", 1)[-1].split("/", 1)[-1]):
        return "login", ""
    txt = r.text
    logged_in = (
        f'"USER_ID":"{uid}"' in txt
        or f"c_user={uid}" in txt
        or f"view_as_entry_list" in txt and uid in txt
        or bool(_extract(txt, _DTSG_PATTERNS))
    )
    if logged_in:
        return "ok", txt
    if "loginform" in txt or "login_form" in txt:
        return "login", ""
    # bố cục lạ: vẫn thử tiếp các bước sau
    return "ok", txt


def _tokens_from_html(html_text: str):
    return _extract(html_text, _DTSG_PATTERNS), _extract(html_text, _LSD_PATTERNS)


def _tokens(s: requests.Session):
    """Lấy fb_dtsg + lsd từ trang chủ (fallback nếu probe chưa có)."""
    for url in ("https://www.facebook.com/", "https://www.facebook.com/me/"):
        try:
            r = s.get(url, timeout=25)
            if r.status_code == 200 and "login" not in str(r.url):
                dtsg, lsd = _tokens_from_html(r.text)
                if dtsg:
                    return dtsg, lsd
        except Exception:
            continue
    return "", ""


_VIEWER_UID = ""


def _thread_node(node: dict, tid: str) -> dict:
    """Chuyển 1 node GraphQL thành {id, name, type, count, snippet}."""
    name = _sanitize(node.get("name") or "")
    ppl = []
    try:
        for p in (node.get("all_participants") or {}).get("nodes") or []:
            act = p.get("messaging_actor") or {}
            nm = _sanitize(act.get("name") or "")
            if nm and str(act.get("id")) != _VIEWER_UID:
                ppl.append(nm)
    except Exception:
        pass
    if not name and ppl:
        name = ", ".join(ppl[:3]) + ("…" if len(ppl) > 3 else "")
    snippet = ""
    try:
        lm = (node.get("last_message") or {}).get("nodes") or []
        if lm:
            snippet = (lm[0].get("snippet") or "")[:80]
    except Exception:
        pass
    return {
        "id": tid,
        "name": name,
        "type": node.get("thread_type") or "",
        "count": node.get("messages_count") or 0,
        "snippet": snippet,
    }


def _graphql_threads(s: requests.Session, dtsg: str, lsd: str):
    """Thử các doc_id để lấy list box."""
    if not dtsg:
        return []
    variables = {
        "limit": 50, "before": None, "after": None, "tags": ["INBOX"],
        "includeDeliveryReceipts": False, "includeSeqID": False,
    }
    for doc in THREAD_DOC_IDS:
        try:
            r = s.post("https://www.facebook.com/api/graphql/", timeout=30,
                       data={"fb_dtsg": dtsg, "doc_id": doc, "lsd": lsd or "",
                             "variables": json.dumps(variables)})
            if r.status_code != 200 or '"thread_key"' not in r.text:
                continue
            data = json.loads(r.text)
            found = []

            def walk(o, depth=0):
                if depth > 8:
                    return
                if isinstance(o, dict):
                    if "thread_key" in o and isinstance(o["thread_key"], dict):
                        tk = o["thread_key"]
                        tid = tk.get("thread_fbid") or tk.get("other_user_id")
                        if tid:
                            found.append(_thread_node(o, str(tid)))
                    for v in o.values():
                        walk(v, depth + 1)
                elif isinstance(o, list):
                    for v in o:
                        walk(v, depth + 1)

            walk(data)
            uniq, seen = [], set()
            for b in found:
                if b["id"] not in seen:
                    seen.add(b["id"])
                    uniq.append(b)
            if uniq:
                return uniq
        except Exception:
            continue
    return []


def _parse_html_threads(page: str):
    boxes, seen = [], set()
    pats = [
        r'href="(?:https?://[^"]*)?/messages/(?:read/\?tid=|t/)(\d{6,})[^"]*"[^>]*>(.*?)</a>',
        r'"thread_fbid":"(\d{6,})"',
        r'&quot;thread_fbid&quot;:&quot;(\d{6,})&quot;',
        r'\\"thread_fbid\\":\\"(\d{6,})\\"',
    ]
    for pat in pats:
        for m in re.finditer(pat, page, re.S):
            tid = m.group(1)
            if tid in seen:
                continue
            name = _clean(m.group(2)) if (m.lastindex or 0) >= 2 else ""
            seen.add(tid)
            boxes.append({"id": tid, "name": name if len(name) < 120 else ""})
    return boxes


def _html_threads(s: requests.Session):
    # 1) m.facebook.com với UA MOBILE — bản server-render còn trả link box
    try:
        s.headers.update(_headers(s.headers.get("Cookie", ""), UA_MOBILE))
        s.headers["sec-ch-ua-mobile"] = "?1"
        s.headers["sec-ch-ua-platform"] = '"Android"'
        r = s.get("https://m.facebook.com/messages/", timeout=20)
        if r.status_code == 200 and "login" not in str(r.url):
            boxes = _parse_html_threads(r.text)
            if boxes:
                return boxes
    except Exception:
        pass
    finally:
        # trả UA desktop như ban đầu
        s.headers.update(_headers(s.headers.get("Cookie", ""), UA_DESKTOP))
        s.headers["sec-ch-ua-mobile"] = "?0"
        s.headers["sec-ch-ua-platform"] = '"Windows"'
    # 2) www messages (dữ liệu JSON nhúng)
    for url in ("https://www.facebook.com/messages/t/",):
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200 or "login" in str(r.url):
                continue
            boxes = _parse_html_threads(r.text)
            if boxes:
                return boxes
        except Exception:
            continue
    return []


def get_info(cookie: str) -> dict:
    """Trả về {uid, name, boxes, count, note} hoặc raise ValueError khi cookie chết."""
    if not cookie or "c_user=" not in cookie:
        raise ValueError("Cookie không hợp lệ (thiếu c_user)")
    uid = get_uid(cookie)
    global _VIEWER_UID
    _VIEWER_UID = uid
    s = _session(cookie)

    # ---- probe session: fail fast khi cookie chết ----
    status, home_html = _probe_session(s, uid)
    if status == "checkpoint":
        raise ValueError(
            "Tài khoản đang bị checkpoint/khoá — hãy đăng nhập web facebook.com để mở khoá rồi lấy lại cookie.")
    if status == "login":
        raise ValueError(
            "Cookie ĐÃ HẾT HẠN hoặc không hợp lệ (Facebook xoá session, bắt đăng nhập lại). "
            "Hãy lấy cookie MỚI: đăng nhập facebook.com trong trình duyệt → F12 → Application → Cookies → copy c_user + xs + datr + fr, dán lại vào đây.")

    dtsg, lsd = _tokens_from_html(home_html)
    if not dtsg:
        dtsg, lsd = _tokens(s)

    note = ""
    name, boxes = "", []
    try:
        name = get_name(s, uid)
        if dtsg:
            boxes = _graphql_threads(s, dtsg, lsd)
        if not boxes:
            time.sleep(0.6)
            boxes = _html_threads(s)
        if not boxes:
            note = ("Đăng nhập OK nhưng không đọc được danh sách box (inbox trống, "
                    "Facebook tạm chặn hoặc cookie thiếu quyền Messenger). UID + tên vẫn dùng được.")
    finally:
        try:
            s.close()
        except Exception:
            pass
    return {
        "uid": uid,
        "name": _sanitize(name) or "(không lấy được tên)",
        "boxes": boxes,
        "count": len(boxes),
        "note": note,
    }

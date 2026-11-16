"""Facebook info helpers: lấy UID, tên và danh sách box (thread) từ cookie.

Không gửi tin nhắn — chỉ đọc thông tin tài khoản & hội thoại.
Chiến lược: www (full browser headers) + GraphQL thread list, fallback mbasic.
"""
import re
import json
import html
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# doc_id của query "MessengerThreadList" (thay đổi theo thời gian, thử lần lượt)
THREAD_DOC_IDS = [
    "1349387578499440",
    "3336396838921549",
    "7731783905042825",
    "9210108100896373",
    "7045423711033265",
]


def _headers(cookie: str) -> dict:
    return {
        "Cookie": cookie,
        "User-Agent": UA,
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


def _tokens(s: requests.Session):
    """Lấy fb_dtsg + lsd từ trang chủ."""
    try:
        r = s.get("https://www.facebook.com/", timeout=25)
        if r.status_code != 200:
            return None, None
        m = (re.search(r'"DTSGInitialData",\[\],\{"token":"(.*?)"', r.text)
             or re.search(r'name="fb_dtsg"\s+value="(.*?)"', r.text))
        dtsg = m.group(1) if m else None
        m2 = re.search(r'"LSD",\[\],\{"token":"(.*?)"', r.text)
        return dtsg, (m2.group(1) if m2 else "")
    except Exception:
        return None, None


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
    for url in ("https://mbasic.facebook.com/messages/",
                "https://www.facebook.com/messages/t/",
                "https://m.facebook.com/messages/"):
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200:
                continue
            boxes = _parse_html_threads(r.text)
            if boxes:
                return boxes
        except Exception:
            continue
    return []


def get_info(cookie: str) -> dict:
    """Trả về {uid, name, boxes, count, note}."""
    if not cookie or "c_user=" not in cookie:
        raise ValueError("Cookie không hợp lệ (thiếu c_user)")
    uid = get_uid(cookie)
    global _VIEWER_UID
    _VIEWER_UID = uid
    s = _session(cookie)
    note = ""
    name, boxes = "", []
    try:
        name = get_name(s, uid)
        dtsg, lsd = _tokens(s)
        if dtsg:
            boxes = _graphql_threads(s, dtsg, lsd)
        if not boxes:
            time.sleep(0.6)
            boxes = _html_threads(s)
        if not boxes:
            note = ("Không đọc được danh sách box (Facebook có thể đang tạm chặn hoặc cookie thiếu quyền). "
                    "UID vẫn dùng được.")
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

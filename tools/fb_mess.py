"""Facebook Messenger treo tool (port of treomesv7.py).
Cookie + nhiều box (thread_id) + delay + nhiều tài khoản luân phiên.
"""
import time
import re
import json
import gc
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class NamNikolai:
    def __init__(self, cookie):
        self.cookie = cookie
        self.user_id = self.get_user_id()
        self.fb_dtsg = None
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1)
        adapter = HTTPAdapter(pool_connections=3, pool_maxsize=5, max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({"Cookie": self.cookie, "User-Agent": "Mozilla/5.0"})
        self.init_params()

    def get_user_id(self):
        m = re.search(r"c_user=(\d+)", self.cookie)
        if not m:
            raise Exception("Cookie không hợp lệ (thiếu c_user)")
        return m.group(1)

    def init_params(self):
        for url in ("https://mbasic.facebook.com", "https://www.facebook.com", "https://m.facebook.com"):
            try:
                res = self.session.get(url, timeout=10)
                m = re.search(r'name="fb_dtsg" value="(.*?)"', res.text) or re.search(r'"token":"(.*?)"', res.text)
                if m:
                    self.fb_dtsg = m.group(1)
                    return
            except Exception:
                continue
        raise Exception("Không tìm thấy fb_dtsg")

    def refresh(self):
        try:
            self.init_params()
        except Exception:
            pass

    def cleanup(self):
        try:
            self.session.close()
            gc.collect()
        except Exception:
            pass

    def send(self, recipient_id, message):
        ts = int(time.time() * 1000)
        data = {
            "fb_dtsg": self.fb_dtsg, "__user": self.user_id, "body": message,
            "action_type": "ma-type:user-generated-message", "timestamp": ts,
            "offline_threading_id": str(ts), "message_id": str(ts),
            "thread_fbid": recipient_id, "source": "source:chat:web", "client": "mercury",
        }
        for attempt in range(3):
            try:
                r = self.session.post("https://www.facebook.com/messaging/send/", data=data,
                                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
                if r.status_code == 200:
                    try:
                        result = json.loads(r.text.replace("for (;;);", ""))
                        if "error" in result and attempt < 2:
                            self.refresh(); data["fb_dtsg"] = self.fb_dtsg; continue
                    except Exception:
                        pass
                    return True, "OK"
                if r.status_code == 429:
                    return False, "Rate limited"
                if r.status_code in (401, 403):
                    return False, "Cookie die"
                if attempt < 2:
                    self.refresh(); data["fb_dtsg"] = self.fb_dtsg; continue
                return False, f"HTTP {r.status_code}"
            except Exception as e:
                if attempt < 2:
                    self.refresh(); data["fb_dtsg"] = self.fb_dtsg; continue
                return False, str(e)
        return False, "Max attempts"


def _parse_list(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").replace(",", "\n").splitlines() if x.strip()]


def run(config, ctx):
    cookies = _parse_list(config.get("cookies"))
    threads = _parse_list(config.get("threads"))
    messages = _parse_list(config.get("messages"))
    delay = float(config.get("delay", 3) or 3)
    if not cookies or not threads or not messages:
        ctx.log("Thiếu cookie / box / nội dung")
        return

    bots = {}
    for c in cookies:
        try:
            b = NamNikolai(c)
            bots[b.user_id] = b
            ctx.log(f"Cookie UID {b.user_id} OK")
        except Exception as e:
            ctx.log(f"Cookie lỗi: {e}")
    if not bots:
        ctx.log("Không có cookie hợp lệ")
        return

    keys = list(bots.keys())
    i = 0
    while not ctx.stopped:
        ctx.check_pause()
        uid = keys[i % len(keys)]
        bot = bots[uid]
        for th in threads:
            if ctx.stopped:
                break
            for msg in messages:
                if ctx.stopped:
                    break
                ok, err = bot.send(th, msg)
                if ok:
                    ctx.sent()
                    ctx.log(f"✔ {uid} → box {th}")
                else:
                    ctx.log(f"✘ {uid} → box {th}: {err}")
                    if "die" in err.lower():
                        try:
                            bot.refresh()
                        except Exception:
                            pass
                if not ctx.wait(delay):
                    break
        i += 1
        if i % 50 == 0:
            gc.collect()
    for b in bots.values():
        b.cleanup()

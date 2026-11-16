"""Facebook 'nhây mess' tool (port of nhaymess.py):
fake typing qua MQTT + gửi tin nhắn tag mention vào box.
Config: cookie, thread (box id), members (uid hoặc "uid:name" mỗi dòng),
        message, delay, typing (bool)
"""
import time
import re
import json
import ssl
import gc
import random
import string
import hashlib
import requests
from urllib.parse import urlparse

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except Exception:
    MQTT_OK = False


def get_uid(cookie):
    m = re.search(r"c_user=(\d+)", cookie)
    return m.group(1) if m else "0"


def get_fb_dtsg_jazoest(cookie, target_id):
    try:
        r = requests.get(f"https://mbasic.facebook.com/privacy/touch/block/confirm/?bid={target_id}",
                         headers={"cookie": cookie}, timeout=15).text
        d = re.search(r'name="fb_dtsg" value="([^"]+)"', r)
        j = re.search(r'name="jazoest" value="([^"]+)"', r)
        if d and j:
            return d.group(1), j.group(1)
    except Exception:
        pass
    return None, None


def _rand(n):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


class NhâyMess:
    def __init__(self, cookie):
        self.cookie = cookie
        self.uid = get_uid(cookie)
        self.fb_dtsg, self.jazoest = get_fb_dtsg_jazoest(cookie, self.uid)
        self.mqtt = None
        self.req = 0
        self.session_id = _rand(8)

    def connect_mqtt(self):
        if not MQTT_OK:
            return False
        try:
            client = mqtt.Client(client_id="mqttwsclient", clean_session=True,
                                 protocol=mqtt.MQTTv31, transport="websockets")
            client.tls_set(certfile=None, keyfile=None, cert_reqs=ssl.CERT_NONE,
                           tls_version=ssl.PROTOCOL_TLSv1_2)
            user_config = {
                "u": self.uid, "s": self.session_id, "chat_on": "true", "fg": False,
                "d": _rand(16), "ct": "websocket", "aid": 219994525426954,
                "mqtt_sid": "", "cp": 3, "ecp": 10,
                "st": ["/t_ms", "/messenger_sync_get_diffs", "/messenger_sync_create_queue"],
                "pm": [], "dc": "", "no_auto_fg": True, "gas": None, "pack": [],
            }
            client.username_pw_set(username=json.dumps(user_config, separators=(",", ":")))
            host = f"wss://edge-chat.messenger.com/chat?region=eag&sid={self.session_id}"
            p = urlparse(host)
            client.ws_set_options(path=f"{p.path}?{p.query}", headers={
                "Cookie": self.cookie, "Origin": "https://www.messenger.com",
                "User-Agent": "Mozilla/5.0", "Referer": "https://www.messenger.com/",
                "Host": "edge-chat.messenger.com",
            })
            client.connect("edge-chat.messenger.com", 443, 10)
            client.loop_start()
            self.mqtt = client
            return True
        except Exception:
            self.mqtt = None
            return False

    def typing(self, thread_id, on=True):
        if not self.mqtt:
            return
        self.req += 1
        payload = {"thread_key": thread_id, "is_group_thread": 1,
                   "is_typing": 1 if on else 0, "attribution": 0}
        content = {
            "app_id": "2220391788200892",
            "payload": json.dumps({"label": "3", "payload": json.dumps(payload, separators=(",", ":")),
                                   "version": "25393437286970779"}, separators=(",", ":")),
            "request_id": self.req, "type": 4,
        }
        try:
            self.mqtt.publish("/ls_req", json.dumps(content, separators=(",", ":")), qos=1)
        except Exception:
            pass

    def send_mention(self, thread_id, body, members):
        profile = []
        for m in members:
            uid = m.get("uid")
            name = m.get("name") or f"UID_{uid}"
            tag = f"@{name}"
            pos = len(body)
            body += f" {tag}"
            profile.append({"id": uid, "offset": pos + 1, "length": len(tag), "type": "p"})
        ts = str(int(time.time() * 1000))
        data = {
            "thread_fbid": thread_id, "action_type": "ma-type:user-generated-message",
            "body": body, "client": "mercury", "author": f"fbid:{self.uid}",
            "timestamp": ts, "offline_threading_id": ts, "message_id": ts,
            "source": "source:chat:web", "__user": self.uid, "__a": "1", "__req": "1b",
            "__rev": "1015919737", "fb_dtsg": self.fb_dtsg or "", "jazoest": self.jazoest or "",
        }
        for i, x in enumerate(profile):
            data[f"profile_xmd[{i}][id]"] = x["id"]
            data[f"profile_xmd[{i}][offset]"] = str(x["offset"])
            data[f"profile_xmd[{i}][length]"] = str(x["length"])
            data[f"profile_xmd[{i}][type]"] = x["type"]
        try:
            r = requests.post("https://www.facebook.com/messaging/send/", data=data, timeout=30,
                              headers={"Cookie": self.cookie, "User-Agent": "Mozilla/5.0",
                                       "Content-Type": "application/x-www-form-urlencoded"})
            return r.status_code == 200
        except Exception:
            return False

    def close(self):
        try:
            if self.mqtt:
                self.mqtt.disconnect()
                self.mqtt.loop_stop()
        except Exception:
            pass
        gc.collect()


def _parse_members(raw):
    out = []
    for line in str(raw or "").replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            uid, name = line.split(":", 1)
            out.append({"uid": uid.strip(), "name": name.strip()})
        else:
            out.append({"uid": line, "name": f"UID_{line}"})
    return out


def run(config, ctx):
    cookie = str(config.get("cookie", "")).strip()
    thread = str(config.get("thread", "")).strip()
    message = config.get("message", "")
    use_typing = bool(config.get("typing", True))
    members = _parse_members(config.get("members"))
    if not cookie or not thread or not message:
        ctx.log("Thiếu cookie / box / nội dung")
        return
    bot = NhâyMess(cookie)
    if not bot.fb_dtsg:
        ctx.log("Không lấy được fb_dtsg — cookie có thể die")
        return
    if use_typing:
        if bot.connect_mqtt():
            ctx.log("Đã kết nối MQTT (fake typing)")
        else:
            ctx.log("Không kết nối được MQTT, vẫn gửi tin bình thường")
    ctx.log(f"Nhây box {thread}, {len(members)} member tag — delay = giây giữa các lần nhây, áp dụng ngay khi sửa")
    next_t = time.time()
    while not ctx.stopped:
        ctx.check_pause()
        # delay đọc LIVE mỗi vòng — sửa config là ăn ngay
        delay = ctx.interval("delay", 3)
        try:
            if use_typing:
                bot.typing(thread, True)
                if not ctx.wait(min(random.uniform(1.5, 3), delay * 0.5)):
                    break
            ok = bot.send_mention(thread, message, members)
            if ok:
                ctx.sent()
                ctx.log(f"✔ Đã nhây box {thread}")
            else:
                ctx.log(f"✘ Gửi thất bại box {thread}")
            if use_typing:
                bot.typing(thread, False)
        except Exception as e:
            ctx.log(f"Lỗi: {e}")
        # fixed-rate: lần nhây kế bắt đầu đúng `delay` giây kể từ BẮT ĐẦU lần này
        next_t = ctx.pace(next_t, delay)
        if next_t is None:
            break
    bot.close()

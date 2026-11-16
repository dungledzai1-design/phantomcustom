"""Zalo đa năng (port of zalonhieucn.py) — 10 chế độ:
nhaytag, treongon, spamcall, treoanh, doitennhom, doianhnhom,
spamsticker, spamvoice, spamcard, join.
"""
import os
import time
import json
import random
import re

try:
    from zlapi import ThreadType, Message, Mention, MultiMention
    ZLAPI_OK = True
except Exception:
    ZLAPI_OK = False

from .zalo_session import login as zalo_login, auto_groups, ZaloSessionError

try:
    from gtts import gTTS
    GTTS_OK = True
except Exception:
    GTTS_OK = False


def _parse_list(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").replace(",", "\n").splitlines() if x.strip()]


def _cookies(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _extract_gid(link):
    s = str(link or "").strip()
    # chấp nhận dòng "UID — Tên nhóm" / "UID - Tên" / "UID | Tên" (web điền kèm tên)
    s = re.split(r"\s+[—|]\s+|\s+-\s+", s, maxsplit=1)[0].strip()
    for pat in (r"zalo\.me/g/([a-zA-Z0-9_-]+)", r"/g/([a-zA-Z0-9_-]+)"):
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return s if s and not s.startswith("http") else None


def _images(folder):
    try:
        return [os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]
    except Exception:
        return []


class ZaloMulti:
    def __init__(self, config, ctx):
        self.cfg = config
        self.ctx = ctx
        self.imei = str(config.get("imei", ""))
        self.raw_cookies = config.get("cookies")
        self.mode = config.get("mode", "nhaytag")
        self.groups = [g for g in (_extract_gid(x) for x in _parse_list(config.get("groups"))) if g]
        self.message = config.get("message", "")
        self.messages = _parse_list(config.get("messages")) or ([self.message] if self.message else [])
        # delay đọc LIVE qua ctx.interval mỗi vòng — không giữ giá trị cũ lúc start
        self.tag_multiple = bool(config.get("tag_multiple", False))
        self.tag_random = bool(config.get("tag_random", False))
        self.members = _parse_list(config.get("members"))
        self.repeat = int(config.get("repeat_count", 10) or 10)
        self.image_folder = config.get("image_folder", "")
        self.sticker_count = int(config.get("sticker_count", 10) or 10)
        self.join_link = config.get("join_link", "")
        self.bot = None

    def connect(self):
        if not self.imei and not self.raw_cookies:
            self.ctx.log("Thiếu IMEI và cookie — dán IMEI + session cookie Zalo là chạy.")
            return False
        try:
            self.bot = zalo_login(self.imei, self.raw_cookies)
            return True
        except ZaloSessionError as e:
            self.ctx.log(f"❌ {e}")
            return False
        except Exception as e:
            self.ctx.log(f"❌ Không đăng nhập được Zalo: {e}")
            return False

    def _members_for(self, gid):
        if self.members:
            return self.members
        try:
            info = self.bot.fetchGroupMembers(gid)
            return list(info.keys()) if info else []
        except Exception:
            return []

    def run(self):
        if not ZLAPI_OK:
            self.ctx.log("Thiếu thư viện zlapi.")
            return
        if not self.connect():
            return
        if self.mode == "join":
            self._join()
            return
        if not self.groups:
            self.ctx.log("🔎 Chưa nhập box — đang tự đọc danh sách nhóm từ tài khoản...")
            self.groups = auto_groups(self.bot)
            if not self.groups:
                self.ctx.log("❌ Tài khoản không có nhóm nào để chạy.")
                return
            self.ctx.log(f"✅ Tự phát hiện {len(self.groups)} nhóm — bắt đầu mode {self.mode}.")
        for gid in self.groups:
            if self.ctx.stopped:
                break
            self.ctx.log(f"Bắt đầu mode {self.mode} → nhóm {gid}")
            try:
                getattr(self, f"_mode_{self.mode}")(gid)
            except Exception as e:
                self.ctx.log(f"Lỗi nhóm {gid}: {e}")

    # ---- modes ----
    def _dmin(self):
        return self.ctx.interval("delay_min", 2)

    def _dmax(self, dmin):
        return max(dmin, self.ctx.interval("delay_max", dmin))

    def _mode_nhaytag(self, gid):
        members = self._members_for(gid)
        if not members:
            self.ctx.log("Không có member để tag")
            return
        idx = 0
        next_t = time.time()
        while not self.ctx.stopped and self.messages:
            self.ctx.check_pause()
            dmin = self._dmin()
            dmax = self._dmax(dmin)
            raw = random.choice(self.messages)
            try:
                if self.tag_multiple:
                    users = members[:]
                    if self.tag_random:
                        random.shuffle(users)
                    names = []
                    for uid in users:
                        try:
                            info = self.bot.fetchUserInfo(uid)
                            names.append((uid, info.changed_profiles[uid]["displayName"]))
                        except Exception:
                            continue
                    body = raw + " " + " ".join(f"@{n}" for _, n in names)
                    mentions = []
                    for uid, n in names:
                        off = body.find(f"@{n}")
                        mentions.append(Mention(uid, length=len(f"@{n}"), offset=off, auto_format=False))
                    self.bot.setTyping(gid, ThreadType.GROUP)
                    self.bot.send(Message(text=body, mention=MultiMention(mentions)),
                                  thread_id=gid, thread_type=ThreadType.GROUP)
                else:
                    uid = random.choice(members) if self.tag_random else members[idx % len(members)]
                    try:
                        info = self.bot.fetchUserInfo(uid)
                        name = info.changed_profiles[uid]["displayName"]
                    except Exception:
                        name = f"UID_{uid}"
                    body = f"{raw} @{name}"
                    self.bot.setTyping(gid, ThreadType.GROUP)
                    self.bot.send(Message(text=body, mention=Mention(uid, offset=len(raw) + 1, length=len(f"@{name}"))),
                                  thread_id=gid, thread_type=ThreadType.GROUP)
                    idx += 1
                self.ctx.sent()
                self.ctx.log(f"Đã tag nhóm {gid}")
            except Exception as e:
                self.ctx.log(f"Lỗi tag: {e}")
            # fixed-rate: lần tag kế bắt đầu đúng delay giây kể từ BẮT ĐẦU lần này
            next_t = self.ctx.pace(next_t, random.uniform(dmin, dmax))
            if next_t is None:
                break

    def _mode_treongon(self, gid):
        next_t = time.time()
        while not self.ctx.stopped and self.message:
            self.ctx.check_pause()
            dmin = self._dmin()
            try:
                self.bot.setTyping(gid, ThreadType.GROUP)
                self.ctx.wait(min(2.0, dmin * 0.4))
                self.bot.send(Message(text=self.message, mention=Mention("-1", length=len(self.message), offset=0)),
                              thread_id=gid, thread_type=ThreadType.GROUP)
                self.ctx.sent()
                self.ctx.log(f"Treo ngôn → {gid}")
            except Exception as e:
                self.ctx.log(f"Lỗi: {e}")
            next_t = self.ctx.pace(next_t, dmin)
            if next_t is None:
                break

    def _mode_spamcall(self, gid):
        members = self._members_for(gid)
        counts = {u: 0 for u in members}
        while not self.ctx.stopped and members:
            self.ctx.check_pause()
            for uid in list(members):
                if self.ctx.stopped:
                    break
                if counts.get(uid, 0) >= self.repeat:
                    continue
                try:
                    self.bot.sendCall(uid)
                    counts[uid] = counts.get(uid, 0) + 1
                    self.ctx.sent()
                    self.ctx.log(f"Call {uid} lần {counts[uid]}/{self.repeat}")
                    self.ctx.wait(0.5)
                except Exception as e:
                    self.ctx.log(f"Lỗi call {uid}: {e}")
                self.ctx.wait(0.5)  # sàn an toàn cho call, tránh lỗi gọi dồn
            if all(counts.get(u, 0) >= self.repeat for u in members):
                self.ctx.log("Đã call đủ số lần")
                break

    def _mode_treoanh(self, gid):
        imgs = _images(self.image_folder)
        if not imgs:
            self.ctx.log("Không có ảnh trong thư mục")
            return
        i = 0
        next_t = time.time()
        while not self.ctx.stopped:
            self.ctx.check_pause()
            dmin = self._dmin()
            try:
                self.bot.setTyping(gid, ThreadType.GROUP)
                self.ctx.wait(min(2.0, dmin * 0.4))
                self.bot.sendLocalImage(imgs[i % len(imgs)], thread_id=gid,
                                        thread_type=ThreadType.GROUP, width=828, height=1792)
                self.ctx.sent()
                i += 1
                self.ctx.log(f"Gửi ảnh → {gid}")
            except Exception as e:
                self.ctx.log(f"Lỗi ảnh: {e}")
            next_t = self.ctx.pace(next_t, dmin)
            if next_t is None:
                break

    def _mode_doitennhom(self, gid):
        next_t = time.time()
        while not self.ctx.stopped and self.messages:
            for name in self.messages:
                if self.ctx.stopped:
                    break
                dmin = self._dmin()
                try:
                    self.bot.changeGroupName(name.strip(), gid)
                    self.ctx.sent()
                    self.ctx.log(f"Đổi tên nhóm: {name}")
                except Exception as e:
                    self.ctx.log(f"Lỗi đổi tên: {e}")
                next_t = self.ctx.pace(next_t, dmin)
                if next_t is None:
                    break

    def _mode_doianhnhom(self, gid):
        imgs = _images(self.image_folder)
        if not imgs:
            self.ctx.log("Không có ảnh")
            return
        for i in range(self.repeat):
            if self.ctx.stopped:
                break
            dmin = self._dmin()
            try:
                self.bot.changeGroupAvatar(groupId=gid, filePath=random.choice(imgs))
                self.ctx.sent()
                self.ctx.log(f"Đổi avatar nhóm {gid}")
            except Exception as e:
                self.ctx.log(f"Lỗi avatar: {e}")
            if not self.ctx.wait(dmin):
                break

    def _mode_spamsticker(self, gid):
        for _ in range(self.sticker_count):
            if self.ctx.stopped:
                break
            dmin = self._dmin()
            try:
                self.bot.sendSticker(3, "23339", "10425", gid, ThreadType.GROUP)
                self.ctx.sent()
                self.ctx.log("Gửi sticker")
            except Exception as e:
                self.ctx.log(f"Lỗi sticker: {e}")
            if not self.ctx.wait(dmin):
                break

    def _mode_spamvoice(self, gid):
        if not GTTS_OK:
            self.ctx.log("Thiếu gtts")
            return
        next_t = time.time()
        while not self.ctx.stopped and self.messages:
            for text in self.messages:
                if self.ctx.stopped:
                    break
                dmin = self._dmin()
                try:
                    fn = f"voice_{int(time.time())}.mp3"
                    gTTS(text=text, lang="vi").save(fn)
                    self.bot.sendLocalVoice(fn, thread_id=gid, thread_type=ThreadType.GROUP)
                    self.ctx.sent()
                    self.ctx.log(f"Gửi voice: {text[:20]}")
                    try:
                        os.remove(fn)
                    except Exception:
                        pass
                except Exception as e:
                    self.ctx.log(f"Lỗi voice: {e}")
                # gTTS tạo file mất thời gian — fixed-rate bù trôi, giữ đúng delay
                next_t = self.ctx.pace(next_t, dmin)
                if next_t is None:
                    break

    def _mode_spamcard(self, gid):
        members = self._members_for(gid)
        next_t = time.time()
        while not self.ctx.stopped and members:
            for uid in members:
                if self.ctx.stopped:
                    break
                for phone in self.messages:
                    if self.ctx.stopped:
                        break
                    dmin = self._dmin()
                    try:
                        info = self.bot.fetchUserInfo(uid).changed_profiles.get(uid)
                        avatar = info.get("avatar") if info else None
                        if not avatar:
                            continue
                        self.bot.sendBusinessCard(userId=uid, phone=phone.strip(), qrCodeUrl=avatar,
                                                  thread_id=gid, thread_type=ThreadType.GROUP)
                        self.ctx.sent()
                        self.ctx.log(f"Gửi danh thiếp {uid}")
                    except Exception as e:
                        self.ctx.log(f"Lỗi card: {e}")
                    next_t = self.ctx.pace(next_t, dmin)
                    if next_t is None:
                        break

    def _join(self):
        links = _parse_list(self.join_link)
        for link in links:
            if self.ctx.stopped:
                break
            try:
                gid = _extract_gid(link)
                if gid:
                    self.bot.joinGroup(gid)
                    self.ctx.sent()
                    self.ctx.log(f"Join nhóm {gid}")
            except Exception as e:
                self.ctx.log(f"Lỗi join: {e}")
            if not self.ctx.wait(self._dmin()):
                break


def run(config, ctx):
    ZaloMulti(config, ctx).run()

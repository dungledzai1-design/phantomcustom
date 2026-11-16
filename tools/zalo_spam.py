"""Zalo treo tool (port of 1.py) — spam text / ảnh / video vào nhiều nhóm.

Config keys:
  imei (bắt buộc), cookies (JSON string or dict — bắt buộc), groups (list/text,
  để trống = tự đọc toàn bộ nhóm đang tham gia), message, delay, ttl,
  colors (list of 1..4), media_type (none|image|video),
  media_source (folder path or newline list of urls)
"""
import time
import json
import random
import os
import re

try:
    from zlapi import ThreadType, Message, Mention, MultiMsgStyle, MessageStyle
    ZLAPI_OK = True
except Exception:
    ZLAPI_OK = False

from .zalo_session import login as zalo_login, auto_groups, ZaloSessionError

COLOR_MAP = {1: "#db342e", 2: "#f27806", 3: "#f7b503", 4: "#15a85f"}


def _parse_list(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").replace(",", "\n").splitlines() if x.strip()]


def _extract_group_id(link):
    s = str(link or "").strip()
    # chấp nhận dòng "UID — Tên nhóm" / "UID - Tên" / "UID | Tên" (web điền kèm tên)
    s = re.split(r"\s+[—|]\s+|\s+-\s+", s, maxsplit=1)[0].strip()
    for pat in (r"zalo\.me/g/([a-zA-Z0-9_-]+)", r"zalo\.me/pc/g/([a-zA-Z0-9_-]+)", r"/g/([a-zA-Z0-9_-]+)"):
        m = re.search(pat, s)
        if m:
            return m.group(1)
    if s and not s.startswith("http"):
        return s
    return None


def _cookies(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _images(folder):
    try:
        exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        return [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    except Exception:
        return []


def run(config, ctx):
    if not ZLAPI_OK:
        ctx.log("Thiếu thư viện zlapi — thêm 'zlapi' vào requirements để chạy tool Zalo.")
        return
    imei = str(config.get("imei", "")).strip()
    raw_cookies = config.get("cookies")
    groups = [_extract_group_id(g) for g in _parse_list(config.get("groups"))]
    groups = [g for g in groups if g]
    message = config.get("message", "")
    ttl = config.get("ttl")
    ttl = int(ttl) if str(ttl).strip().isdigit() else None
    colors = config.get("colors") or [1, 2, 3, 4]
    if isinstance(colors, str):
        colors = [int(x) for x in re.findall(r"\d", colors)] or [1, 2, 3, 4]
    media_type = config.get("media_type", "none")
    media_source = config.get("media_source", "")

    if not imei and not raw_cookies:
        ctx.log("Thiếu IMEI và cookie — dán IMEI + session cookie Zalo là chạy.")
        return

    try:
        bot = zalo_login(imei, raw_cookies)
    except ZaloSessionError as e:
        ctx.log(f"❌ {e}")
        return
    except Exception as e:
        ctx.log(f"❌ Không đăng nhập được Zalo: {e}")
        return

    # Không nhập link box → tự đọc toàn bộ nhóm đang tham gia
    if not groups:
        ctx.log("🔎 Chưa nhập box — đang tự đọc danh sách nhóm từ tài khoản...")
        groups = auto_groups(bot)
        if not groups:
            ctx.log("❌ Tài khoản không có nhóm nào (hoặc cookie không đủ quyền đọc nhóm).")
            return
        ctx.log(f"✅ Tự phát hiện {len(groups)} nhóm — bắt đầu treo.")

    ctx.log(f"Đã đăng nhập bằng IMEI + cookie, treo {len(groups)} nhóm — delay = giây giữa các tin, áp dụng ngay khi sửa")
    color_index = 0
    last_video = -1
    next_t = time.time()
    while not ctx.stopped:
        ctx.check_pause()
        for gid in groups:
            if ctx.stopped:
                break
            # delay đọc LIVE mỗi tin — sửa config là ăn ngay
            delay = ctx.interval("delay", 5)
            typing_wait = min(2.0, delay * 0.4)  # fake đang gõ, không ăn quá sâu vào slot delay
            try:
                bot.setTyping(gid, ThreadType.GROUP)
                if not ctx.wait(typing_wait):
                    break

                if media_type == "image":
                    files = _images(media_source)
                    if files:
                        bot.sendLocalImage(random.choice(files), thread_id=gid,
                                           thread_type=ThreadType.GROUP, width=1920, height=1080, ttl=ttl)
                        ctx.sent()
                        ctx.log(f"📸 Gửi ảnh → {gid}")
                elif media_type == "video":
                    urls = _parse_list(media_source)
                    if urls:
                        idx = random.randint(0, len(urls) - 1)
                        while idx == last_video and len(urls) > 1:
                            idx = random.randint(0, len(urls) - 1)
                        last_video = idx
                        bot.sendRemoteVideo(urls[idx],
                                            "https://f67-zpg-r.zdn.vn/jpg/5430817190992001544/90772e3e11239c7dc532.jpg",
                                            duration="100000", thread_id=gid, thread_type=ThreadType.GROUP,
                                            width=1920, height=1080, ttl=ttl)
                        ctx.sent()
                        ctx.log(f"🎬 Gửi video → {gid}")

                if message:
                    mention = Mention("-1", length=len(message), offset=0)
                    color = COLOR_MAP.get(colors[color_index % len(colors)], "#db342e")
                    style = MultiMsgStyle([
                        MessageStyle(offset=0, length=1000, style="color", color=color, auto_format=False),
                        MessageStyle(offset=0, length=1000, style="font", size="40", auto_format=False),
                    ])
                    msg = Message(text=message, mention=mention, style=style)
                    if ttl:
                        bot.send(msg, thread_id=gid, thread_type=ThreadType.GROUP, ttl=ttl)
                    else:
                        bot.send(msg, thread_id=gid, thread_type=ThreadType.GROUP)
                    ctx.sent()
                    color_index += 1
                    ctx.log(f"💬 Gửi tin → {gid} (màu {colors[(color_index - 1) % len(colors)]})")
            except Exception as e:
                ctx.log(f"Lỗi nhóm {gid}: {e}")
            # fixed-rate: tin kế bắt đầu đúng `delay` giây kể từ BẮT ĐẦU tin này
            next_t = ctx.pace(next_t, delay)
            if next_t is None:
                break

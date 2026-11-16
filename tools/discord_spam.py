"""Discord tools: treodis (multi token + multi channel) and nhaydiscord
(token + UID channel, continuous spam). Faithful port of treodis.py.
"""
import time
import random
import requests

API = "https://discord.com/api/v10"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _headers(token):
    return {"Authorization": token, "Content-Type": "application/json", "User-Agent": UA}


def _check_token(token):
    try:
        r = requests.get(f"{API}/users/@me", headers=_headers(token), timeout=10)
        if r.status_code == 200:
            return r.json().get("username")
    except Exception:
        pass
    return None


def _send(token, channel_id, content, ctx):
    url = f"{API}/channels/{channel_id}/messages"
    try:
        r = requests.post(url, headers=_headers(token), json={"content": content}, timeout=15)
        if r.status_code == 429:
            retry = 1
            try:
                retry = r.json().get("retry_after", 1)
            except Exception:
                pass
            ctx.log(f"Rate limit token ...{token[-5:]} chờ {retry}s")
            ctx.wait(float(retry) + 0.3)
            return _send(token, channel_id, content, ctx)
        if r.status_code in (200, 201):
            ctx.sent()
            ctx.log(f"✔ Token ...{token[-5:]} → channel {channel_id}")
            return True
        ctx.log(f"✘ Token ...{token[-5:]} lỗi {r.status_code}")
    except Exception as e:
        ctx.log(f"Exception token ...{token[-5:]}: {e}")
    return False


def _parse_list(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").replace(",", "\n").splitlines() if x.strip()]


def run_treodis(config, ctx):
    """config: tokens (list/text), channels (list/text), message, delay"""
    tokens = _parse_list(config.get("tokens"))
    channels = _parse_list(config.get("channels"))
    message = config.get("message", "")
    if not tokens or not channels or not message:
        ctx.log("Thiếu token / channel / nội dung")
        return

    valid = []
    for t in tokens:
        name = _check_token(t)
        if name:
            valid.append(t)
            ctx.log(f"Token ...{t[-5:]} hợp lệ ({name})")
        else:
            ctx.log(f"Token ...{t[-5:]} KHÔNG đăng nhập được")
    if not valid:
        ctx.log("Không có token hợp lệ")
        return
    ctx.log(f"Treo Discord: {len(valid)} token × {len(channels)} channel — delay = giây giữa các tin, áp dụng ngay khi sửa")

    next_t = time.time()
    while not ctx.stopped:
        ctx.check_pause()
        for t in valid:
            if ctx.stopped:
                break
            for ch in channels:
                if ctx.stopped:
                    break
                # delay đọc LIVE mỗi tin — sửa config là ăn ngay
                delay = ctx.interval("delay", 5)
                _send(t, ch, message, ctx)
                # fixed-rate: tin kế bắt đầu đúng `delay` giây kể từ BẮT ĐẦU tin này
                next_t = ctx.pace(next_t, delay)
                if next_t is None:
                    break


def run_nhaydiscord(config, ctx):
    """config: token (single), channel (UID), message, delay. Continuous."""
    token = str(config.get("token", "")).strip()
    channel = str(config.get("channel", "")).strip()
    message = config.get("message", "")
    if not token or not channel or not message:
        ctx.log("Thiếu token / UID channel / nội dung")
        return
    name = _check_token(token)
    if not name:
        ctx.log("Token không đăng nhập được")
        return
    ctx.log(f"Nhây Discord bằng {name} vào channel {channel} — delay = giây giữa các tin, áp dụng ngay khi sửa")
    next_t = time.time()
    while not ctx.stopped:
        ctx.check_pause()
        # delay đọc LIVE mỗi tin — sửa config là ăn ngay
        delay = ctx.interval("delay", 2)
        _send(token, channel, message, ctx)
        # fixed-rate: tin kế bắt đầu đúng `delay` giây kể từ BẮT ĐẦU tin này
        next_t = ctx.pace(next_t, delay)
        if next_t is None:
            break

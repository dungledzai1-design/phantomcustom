"""Self-ping giữ Render không ngủ — trái tim của tính năng "treo 24/7".

Bối cảnh: task treo chạy bằng thread BÊN TRONG process server (không phụ thuộc
tab web của người dùng). Nhưng Render free tier suspend process sau ~15 phút
không có request HTTP vào → mọi thread treo đông cứng → user thấy "đóng web là
dừng treo".

Giải pháp: ping /healthz của chính server mỗi KEEPALIVE_SEC giây (mặc định 540s
= 9 phút < 15 phút) → Render luôn thấy traffic → không bao giờ ngủ → thread treo
chạy liên tục dù người dùng đóng tab, tắt máy hay mất mạng.

Env:
  SELF_URL            URL tự trỏ về chính server (mặc định dùng RENDER_EXTERNAL_URL
                      mà Render tự cấp cho web service)
  KEEPALIVE_SEC       chu kỳ ping, mặc định 540
"""
import os
import threading
import time
import urllib.request

_started = False
_interval = 0
_base = ""


def base_url() -> str:
    return (os.environ.get("SELF_URL")
            or os.environ.get("RENDER_EXTERNAL_URL")
            or "").rstrip("/")


def start():
    """Khởi động vòng ping. Idempotent — gọi lại vô hại."""
    global _started, _interval, _base
    if _started:
        return True
    _base = base_url()
    if not _base:
        print("[keepalive] chưa có SELF_URL/RENDER_EXTERNAL_URL — chạy local, bỏ qua self-ping")
        return False
    try:
        _interval = int(os.environ.get("KEEPALIVE_SEC", "540") or 540)
    except ValueError:
        _interval = 540
    _interval = max(60, _interval)

    def _loop():
        while True:
            try:
                r = urllib.request.urlopen(_base + "/healthz", timeout=30)
                r.close()
                print(f"[keepalive] ping ok {_base}/healthz ({time.strftime('%H:%M:%S')})")
            except Exception as e:
                print(f"[keepalive] ping lỗi ({e}) — sẽ thử lại sau {_interval}s")
            time.sleep(_interval)

    threading.Thread(target=_loop, daemon=True, name="keepalive").start()
    _started = True
    print(f"[keepalive] đã bật — tự ping mỗi {_interval}s để server không ngủ, treo 24/7")
    return True


def status():
    return {"enabled": _started, "interval": _interval, "base": _base}

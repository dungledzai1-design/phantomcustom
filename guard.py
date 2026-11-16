"""Lớp bảo vệ tải & ổn định cho PhantomCustom.

- Rate limiter trong bộ nhớ (token bucket) theo IP + nhóm endpoint.
- Giới hạn kích thước request body.
- Giới hạn số kết nối WebSocket đồng thời.
- Bộ đếm/ngưỡng an toàn để server không bao giờ bị "no memory" hay sập.
"""
import time
import threading
from collections import defaultdict, deque

# ------------------------------------------------------------------ rate limit
class RateLimiter:
    """Token bucket đơn giản, an toàn đa luồng, tự dọn key cũ."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_gc = time.time()

    def allow(self, key, limit, window=60.0):
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            # dọn rác mỗi 5 phút để RAM không phình
            if now - self._last_gc > 300:
                self._last_gc = now
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 600]:
                    self._hits.pop(k, None)
            return True


limiter = RateLimiter()

# nhóm endpoint -> (số request, cửa sổ giây)
RULES = [
    ("/api/login", 12, 60),
    ("/api/register", 6, 300),
    ("/api/check", 8, 60),
    ("/api/fb/info", 15, 60),
    ("/api/tasks", 120, 60),
    ("/api/admin", 120, 60),
    ("/api/", 240, 60),
]


def rule_for(path):
    for prefix, limit, window in RULES:
        if path.startswith(prefix):
            return limit, window
    return None, None


# ------------------------------------------------------------------ limits
MAX_BODY_BYTES = 4 * 1024 * 1024      # 4MB / request (đủ cho file acc lớn)
MAX_WS_CONNECTIONS = 500              # tổng WebSocket đồng thời
MAX_WS_PER_USER = 6
MAX_CHECK_LINES = 3000
MAX_CHECK_LINES_ZALO = 250
MAX_TASKS_PER_USER = 300
MAX_RESULTS_RETURN = 3000

_ws_total = 0
_ws_by_user = defaultdict(int)
_ws_lock = threading.Lock()


def ws_acquire(user_id):
    global _ws_total
    with _ws_lock:
        if _ws_total >= MAX_WS_CONNECTIONS:
            return False
        if _ws_by_user[user_id] >= MAX_WS_PER_USER:
            return False
        _ws_total += 1
        _ws_by_user[user_id] += 1
        return True


def ws_release(user_id):
    global _ws_total
    with _ws_lock:
        _ws_total = max(0, _ws_total - 1)
        _ws_by_user[user_id] = max(0, _ws_by_user.get(user_id, 0) - 1)

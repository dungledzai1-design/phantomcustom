"""Task engine: runs many tool tasks concurrently in lightweight threads.

Each task is persisted in SQLite. On server restart, tasks that were running
are automatically resumed so accounts keep "treo" 24/7 until the user stops.
"""
import time
import uuid
import threading
import traceback
import database as db
import tools as registry

MAX_TASKS_PER_USER = 300


class TaskContext:
    def __init__(self, task_id, config, log_cb, sent_cb):
        self.task_id = task_id
        self.config = config or {}
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()  # set = paused
        self._log = log_cb
        self._sent = sent_cb
        # ---- chống die acc (áp dụng cho MỌI tool) ----
        try:
            self.jitter = max(0.0, min(90.0, float(self.config.get("jitter") or 0)))
        except Exception:
            self.jitter = 0.0
        try:
            self.rest_every = max(0, int(self.config.get("rest_every") or 0))
        except Exception:
            self.rest_every = 0
        try:
            self.rest_time = max(0.0, float(self.config.get("rest_time") or 0))
        except Exception:
            self.rest_time = 0.0
        try:
            self.max_sent = max(0, int(self.config.get("max_sent") or 0))
        except Exception:
            self.max_sent = 0
        self._waits = 0
        self._sent_total = 0

    def log(self, msg):
        try:
            self._log(str(msg))
        except Exception:
            pass

    def sent(self, n=1):
        try:
            self._sent(n)
        except Exception:
            pass
        self._sent_total += int(n or 0)
        if self.max_sent and self._sent_total >= self.max_sent:
            self.log(f"🛡 Đã gửi {self._sent_total}/{self.max_sent} tin — tự dừng để bảo vệ acc")
            self.stop_event.set()

    def wait(self, seconds):
        """Sleep that respects stop/pause. Returns False if stopped.

        Tự động thêm jitter ngẫu nhiên + thời gian nghỉ bảo vệ acc.
        """
        import random
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 0.0
        if self.jitter > 0 and seconds > 0:
            seconds *= random.uniform(1 - self.jitter / 100.0, 1 + self.jitter / 100.0)
        self._waits += 1
        if self.rest_every and self.rest_time and self._waits % self.rest_every == 0:
            self.log(f"🛡 Nghỉ bảo vệ acc {self.rest_time:.0f}s (sau {self._waits} lần)")
            seconds += self.rest_time
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self.stop_event.is_set():
                return False
            while self.pause_event.is_set():
                if self.stop_event.is_set():
                    return False
                time.sleep(0.2)
            time.sleep(min(0.2, max(0, end - time.time())))
        return not self.stop_event.is_set()

    @property
    def stopped(self):
        return self.stop_event.is_set()

    def check_pause(self):
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.2)


class RunningTask:
    def __init__(self, row):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.tool = row["tool"]
        self.name = row["name"]
        self.config = row["config"]
        self.status = row.get("status", "running")
        self.created_at = row.get("created_at", time.time())
        self.started_at = row.get("started_at", time.time())
        self.stopped_at = row.get("stopped_at", 0)
        self.sent_count = row.get("sent_count", 0)
        self.last_error = row.get("last_error", "")
        self.logs = []
        self.thread = None
        self.ctx = None
        self._lock = threading.Lock()
        if row.get("log"):
            self.logs = row["log"].splitlines()[-200:]

    def add_log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with self._lock:
            self.logs.append(line)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]

    def add_sent(self, n):
        with self._lock:
            self.sent_count += n

    def uptime(self):
        if self.status == "stopped":
            end = self.stopped_at or time.time()
        else:
            end = time.time()
        return max(0, end - self.started_at)

    def to_dict(self, with_logs=False):
        d = {
            "id": self.id,
            "user_id": self.user_id,
            "tool": self.tool,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "uptime": int(self.uptime()),
            "sent_count": self.sent_count,
            "last_error": self.last_error,
            "config": self.config,
        }
        if with_logs:
            d["logs"] = self.logs[-80:]
        return d


class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.lock = threading.RLock()

    def create(self, user_id, tool, name, config):
        if tool not in registry.TOOLS:
            raise ValueError(f"Tool không tồn tại: {tool}")
        with self.lock:
            mine = sum(1 for t in self.tasks.values() if t.user_id == user_id)
        if mine >= MAX_TASKS_PER_USER:
            raise ValueError(
                f"Đã đạt giới hạn {MAX_TASKS_PER_USER} task/người dùng. "
                "Xoá bớt task cũ rồi tạo tiếp.")
        task_id = uuid.uuid4().hex[:12]
        now = time.time()
        row = {
            "id": task_id, "user_id": user_id, "tool": tool, "name": name,
            "config": config, "status": "running", "created_at": now,
            "started_at": now, "stopped_at": 0, "sent_count": 0,
            "last_error": "", "log": "",
        }
        db.save_task(row)
        rt = RunningTask(row)
        with self.lock:
            self.tasks[task_id] = rt
        self._spawn(rt)
        return rt

    def _spawn(self, rt):
        rt.status = "running"
        rt.ctx = TaskContext(rt.id, rt.config, rt.add_log, rt.add_sent)
        runner = registry.TOOLS[rt.tool]

        def _run():
            try:
                rt.add_log(f"Bắt đầu tool {rt.tool}")
                runner(rt.config, rt.ctx)
                if rt.ctx.stopped:
                    rt.status = "stopped"
                else:
                    rt.status = "finished"
                rt.add_log("Kết thúc task")
            except Exception as e:
                rt.status = "error"
                rt.last_error = str(e)
                rt.add_log("LỖI: " + str(e))
                traceback.print_exc()
            finally:
                if rt.status == "stopped":
                    rt.stopped_at = time.time()
                db.update_task(
                    rt.id, status=rt.status, stopped_at=rt.stopped_at,
                    sent_count=rt.sent_count, last_error=rt.last_error,
                    log="\n".join(rt.logs[-200:]),
                )

        rt.thread = threading.Thread(target=_run, daemon=True)
        rt.thread.start()

    def get(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)

    def list_for_user(self, user_id):
        with self.lock:
            return [t.to_dict() for t in self.tasks.values() if t.user_id == user_id]

    def list_all(self):
        with self.lock:
            return [t.to_dict() for t in self.tasks.values()]

    def stop(self, task_id):
        rt = self.get(task_id)
        if not rt:
            return False
        if rt.ctx:
            rt.ctx.stop_event.set()
            rt.ctx.pause_event.clear()
        rt.status = "stopped"
        rt.stopped_at = time.time()
        db.update_task(task_id, status="stopped", stopped_at=rt.stopped_at)
        rt.add_log("Đã dừng task theo yêu cầu")
        return True

    def pause(self, task_id):
        rt = self.get(task_id)
        if not rt or rt.status != "running":
            return False
        rt.ctx.pause_event.set()
        rt.status = "paused"
        db.update_task(task_id, status="paused")
        rt.add_log("Tạm dừng task")
        return True

    def resume(self, task_id):
        rt = self.get(task_id)
        if not rt:
            return False
        if rt.status == "paused":
            rt.ctx.pause_event.clear()
            rt.status = "running"
            db.update_task(task_id, status="running")
            rt.add_log("Tiếp tục task")
            return True
        if rt.status in ("stopped", "error", "finished"):
            # restart with same config
            rt.started_at = time.time()
            rt.stopped_at = 0
            rt.status = "running"
            rt.sent_count = 0
            rt.logs = []
            db.update_task(task_id, status="running", started_at=rt.started_at,
                           stopped_at=0, sent_count=0, log="")
            self._spawn(rt)
            return True
        return False

    def delete(self, task_id):
        rt = self.get(task_id)
        if rt and rt.ctx:
            rt.ctx.stop_event.set()
        with self.lock:
            self.tasks.pop(task_id, None)
        db.delete_task(task_id)
        return True

    def update_config(self, task_id, config):
        rt = self.get(task_id)
        if not rt:
            return False
        rt.config = config
        if rt.ctx:
            rt.ctx.config = config
        db.update_task(task_id, config=__import__("json").dumps(config, ensure_ascii=False))
        rt.add_log("Đã cập nhật cấu hình (cookie/token/uid/box...)")
        return True

    def stop_all_user(self, user_id):
        with self.lock:
            ids = [t.id for t in self.tasks.values() if t.user_id == user_id]
        for i in ids:
            self.stop(i)
        return len(ids)

    def resume_persisted(self):
        """On startup, resume tasks that were running/paused before restart."""
        rows = db.list_tasks()
        for row in rows:
            if row["status"] in ("running", "paused"):
                rt = RunningTask(row)
                with self.lock:
                    self.tasks[rt.id] = rt
                self._spawn(rt)
                if row["status"] == "paused":
                    rt.ctx.pause_event.set()
                    rt.status = "paused"
        return len(self.tasks)


manager = TaskManager()

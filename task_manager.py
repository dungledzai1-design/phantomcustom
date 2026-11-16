"""Task engine: runs many tool tasks concurrently in lightweight threads.

Each task is persisted in SQLite. On server restart, tasks that were running
are automatically resumed so accounts keep "treo" 24/7 until the user stops.
"""
import os
import time
import uuid
import json
import threading
import traceback
import database as db
import tools as registry

try:
    from backup import schedule_soon
except Exception:  # backup chưa có env -> không sao
    def schedule_soon():
        pass

MAX_TASKS_PER_USER = 300


class TaskContext:
    def __init__(self, task_id, config, log_cb, sent_cb):
        self.task_id = task_id
        self.config = config or {}
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()  # set = paused
        self._log = log_cb
        self._sent = sent_cb

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

    def wait(self, seconds):
        """Sleep that respects stop/pause. Returns False if stopped."""
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 0.0
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

    def wait_until(self, ts):
        """Ngủ tới thời điểm tuyệt đối (epoch giây). Trả False nếu task bị dừng."""
        while True:
            if self.stop_event.is_set():
                return False
            if self.pause_event.is_set():
                time.sleep(0.2)
                continue
            remain = ts - time.time()
            if remain <= 0:
                return True
            time.sleep(min(0.2, remain))

    def interval(self, key, default):
        """Đọc delay từ config MỖI VÒNG (live) — sửa delay ăn ngay khi task đang chạy.

        Sàn 0.5s để tránh đấm API liên tục khi user nhập 0/số âm."""
        raw = (self.config or {}).get(key, default)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            v = float(default)
        return max(0.5, v)

    def pace(self, next_t, delay):
        """Lịch gửi cố định (fixed-rate): tin kế tiếp bắt đầu đúng `delay` giây
        kể từ BẮT ĐẦU tin trước (bù thời gian gửi — không nhanh, không chậm).

        Nếu tin gửi lâu hơn delay (slot đã lùi vào quá khứ) thì KHÔNG burst:
        tin kế chờ đủ `delay` tính từ lúc gửi xong.

        Trả về slot kế tiếp, hoặc None nếu task đã dừng."""
        delay = max(0.5, float(delay or 0.5))
        next_t = next_t + delay
        if next_t < time.time():          # gửi vượt slot — không đuổi các slot đã lỡ
            next_t = time.time() + delay
        return next_t if self.wait_until(next_t) else None

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
        schedule_soon()
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
        schedule_soon()
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
        schedule_soon()
        return True

    def update_config(self, task_id, config):
        rt = self.get(task_id)
        if not rt:
            return False
        config = config or {}
        # MUTATE cùng dict mà runner đang giữ tham chiếu → tool đang chạy thấy
        # cấu hình mới NGAY ở vòng lặp kế (đọc live qua ctx.interval)
        try:
            rt.config.clear()
            rt.config.update(config)
        except Exception:
            rt.config = config
        if rt.ctx:
            rt.ctx.config = rt.config
        db.update_task(task_id, config=json.dumps(config, ensure_ascii=False))
        rt.add_log("Đã cập nhật cấu hình — delay/cookie/token... áp dụng NGAY, không cần restart")
        return True

    def stop_all_user(self, user_id):
        with self.lock:
            ids = [t.id for t in self.tasks.values() if t.user_id == user_id]
        for i in ids:
            self.stop(i)
        return len(ids)

    def delete_all_user(self, user_id):
        """Dừng + xoá toàn bộ task của user (trên RAM và trong DB) — dùng khi xoá user."""
        self.stop_all_user(user_id)
        for t in self.list_for_user(user_id):
            self.delete(t["id"])
        return True

    def start_flusher(self):
        """Ghi định kỳ sent_count + log của task ĐANG CHẠY xuống DB.

        Trước đây bộ đếm chỉ được ghi khi task kết thúc → server restart (deploy,
        Render cold start) là mất số tin đã gửi. Flusher mỗi FLUSH_SEC giây (mặc
        định 60) chụp lại tiến độ → resume_persisted() khôi phục đúng số."""
        if getattr(self, "_flusher_started", False):
            return
        self._flusher_started = True
        try:
            sec = int(os.environ.get("FLUSH_SEC", "60") or 60)
        except ValueError:
            sec = 60
        sec = max(10, sec)

        def _loop():
            while True:
                time.sleep(sec)
                with self.lock:
                    running = [t for t in self.tasks.values() if t.status == "running"]
                for rt in running:
                    try:
                        with rt._lock:
                            sent = rt.sent_count
                            logs = "\n".join(rt.logs[-200:])
                        db.update_task(rt.id, sent_count=sent, log=logs)
                    except Exception:
                        pass

        threading.Thread(target=_loop, daemon=True, name="task-flusher").start()
        print(f"[task-manager] flusher bật — ghi tiến độ task vào DB mỗi {sec}s")

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

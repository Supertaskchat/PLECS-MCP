"""Background task registry with on-disk persistence.

Task records are written to ``~/.plecs-mcp/tasks/<id>.json``. A task that was still
``running``/``pending`` when the server died is reported as ``lost`` after a restart;
small results survive, large ones already live in files via the auto-limit path.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MAX_TASKS = 32
MAX_PERSISTED_RESULT = 200_000


def task_directory() -> Path:
    return Path(os.getenv("PLECS_MCP_TASK_DIR", "~/.plecs-mcp/tasks")).expanduser()


@dataclass
class TaskRecord:
    id: str
    method: str
    status: str = "pending"  # pending | running | done | error | lost
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: Any = None
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        elapsed = (self.finished or time.time()) - (self.started or self.created)
        return {
            "id": self.id,
            "method": self.method,
            "status": self.status,
            "elapsed_seconds": round(elapsed, 3),
            "error": self.error,
        }

    def to_json(self) -> dict[str, Any]:
        result = self.result
        persisted = True
        try:
            encoded = json.dumps(result)
            if len(encoded) > MAX_PERSISTED_RESULT:
                persisted = False
        except (TypeError, ValueError):
            persisted = False
        if not persisted:
            result = {"persisted": False, "note": "result too large or not JSON-serialisable"}
        return {
            "id": self.id,
            "method": self.method,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "result": result,
        }


class TaskRegistry:
    def __init__(self, directory: Path | None = None, load: bool = True) -> None:
        self._directory = directory or task_directory()
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        if load:
            self._load()

    # -- persistence -------------------------------------------------------

    def _path(self, task_id: str) -> Path:
        return self._directory / f"{task_id}.json"

    def _save(self, record: TaskRecord) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._path(record.id).write_text(json.dumps(record.to_json(), default=str), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        try:
            files = sorted(self._directory.glob("*.json"))
        except OSError:
            return
        for path in files[-MAX_TASKS:]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            record = TaskRecord(
                id=data.get("id") or path.stem,
                method=data.get("method", "?"),
                status=data.get("status", "lost"),
                created=float(data.get("created") or 0),
                started=data.get("started"),
                finished=data.get("finished"),
                result=data.get("result"),
                error=data.get("error"),
            )
            if record.status in ("pending", "running"):
                record.status = "lost"
                record.error = "server restarted before the task finished"
                record.finished = time.time()
                self._save(record)
            self._tasks[record.id] = record

    # -- lifecycle ---------------------------------------------------------

    def submit(self, method: str, runner: Callable[[], Any]) -> TaskRecord:
        record = TaskRecord(id=uuid.uuid4().hex[:8], method=method)
        with self._lock:
            self._tasks[record.id] = record
            self._evict_locked()
        self._save(record)

        def work() -> None:
            record.status = "running"
            record.started = time.time()
            self._save(record)
            try:
                record.result = runner()
                record.status = "done"
            except Exception as exc:  # keep the task boundary honest
                record.error = str(exc)
                record.status = "error"
            finally:
                record.finished = time.time()
                self._save(record)

        threading.Thread(target=work, name=f"plecs-task-{record.id}", daemon=True).start()
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda task: task.created, reverse=True)

    def _evict_locked(self) -> None:
        if len(self._tasks) <= MAX_TASKS:
            return
        finished = [task for task in self._tasks.values() if task.status in ("done", "error", "lost")]
        for task in sorted(finished, key=lambda item: item.finished or 0)[: len(self._tasks) - MAX_TASKS]:
            self._tasks.pop(task.id, None)
            try:
                self._path(task.id).unlink(missing_ok=True)
            except OSError:
                pass


TASKS = TaskRegistry()

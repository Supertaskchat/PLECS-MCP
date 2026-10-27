"""Minimal writer-preferring read/write lock.

PLECS serves read-only RPC calls while a simulation runs (measured: statistics in 0.02 s
during a 0.55 s simulate), but accepts only one blocking command at a time. Reads therefore
share the lock; mutating/blocking calls take it exclusively.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager


class ReadWriteLock:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writing = False
        self._waiting_writers = 0

    @contextmanager
    def read(self):
        with self._condition:
            while self._writing or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self):
        with self._condition:
            self._waiting_writers += 1
            while self._writing or self._readers:
                self._condition.wait()
            self._waiting_writers -= 1
            self._writing = True
        try:
            yield
        finally:
            with self._condition:
                self._writing = False
                self._condition.notify_all()

    @property
    def readers(self) -> int:
        return self._readers

    @property
    def writing(self) -> bool:
        return self._writing

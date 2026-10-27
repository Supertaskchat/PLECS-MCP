import threading
import time

from plecs_mcp.locks import ReadWriteLock
from plecs_mcp.client import BLOCKING_METHODS, WRITE_METHODS


def test_readers_run_concurrently():
    lock = ReadWriteLock()
    overlap = {"max": 0, "now": 0}
    guard = threading.Lock()

    def reader():
        with lock.read():
            with guard:
                overlap["now"] += 1
                overlap["max"] = max(overlap["max"], overlap["now"])
            time.sleep(0.1)
            with guard:
                overlap["now"] -= 1

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlap["max"] == 3


def test_writer_excludes_readers():
    lock = ReadWriteLock()
    events = []

    def writer():
        with lock.write():
            events.append("w-in")
            time.sleep(0.1)
            events.append("w-out")

    def reader():
        time.sleep(0.02)
        with lock.read():
            events.append("r-in")

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert events.index("w-out") < events.index("r-in")


def test_lock_classes():
    for method in ("plecs.load", "plecs.set", "plecs.close", "plecs.scope"):
        assert method in WRITE_METHODS
    for method in ("plecs.simulate", "plecs.analyze", "plecs.codegen"):
        assert method in BLOCKING_METHODS and method not in WRITE_METHODS
    for method in ("plecs.get", "plecs.statistics", "plecs.getModelTree", "system.listMethods"):
        assert method not in WRITE_METHODS and method not in BLOCKING_METHODS

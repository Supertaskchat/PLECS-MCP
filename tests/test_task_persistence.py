import json
import time
from pathlib import Path

from plecs_mcp.tasks import TaskRecord, TaskRegistry


def test_records_survive_restart(tmp_path: Path):
    registry = TaskRegistry(directory=tmp_path)
    record = registry.submit("demo", lambda: {"value": 7})
    deadline = time.time() + 5
    while time.time() < deadline and record.status == "running":
        time.sleep(0.01)

    reloaded = TaskRegistry(directory=tmp_path)
    restored = reloaded.get(record.id)
    assert restored is not None
    assert restored.status == "done"
    assert restored.result == {"value": 7}


def test_orphaned_tasks_become_lost(tmp_path: Path):
    orphan = TaskRecord(id="orphan", method="plecs.simulate", status="running")
    (tmp_path / "orphan.json").write_text(json.dumps(orphan.to_json()), encoding="utf-8")
    registry = TaskRegistry(directory=tmp_path)
    restored = registry.get("orphan")
    assert restored.status == "lost"
    assert "restarted" in restored.error


def test_large_results_are_not_persisted(tmp_path: Path):
    record = TaskRecord(id="big", method="demo", status="done", result={"x": "a" * 500_000})
    (tmp_path / "big.json").write_text(json.dumps(record.to_json()), encoding="utf-8")
    payload = json.loads((tmp_path / "big.json").read_text())
    assert payload["result"]["persisted"] is False

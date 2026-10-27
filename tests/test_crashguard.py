"""Tests for crash recognition and the per-file quarantine."""

import os
import time
from pathlib import Path

import pytest

from plecs_mcp import crashguard, server
from plecs_mcp.session import STATE


def test_disconnect_markers():
    assert crashguard.is_disconnect("Server disconnected without sending a response.")
    assert crashguard.is_disconnect("cannot reach PLECS at http://127.0.0.1:1080/")
    assert not crashguard.is_disconnect("Simulation error: singular matrix")


def test_only_compile_calls_are_guarded():
    assert crashguard.is_compile_call("plecs.simulate", ["m"])
    assert crashguard.is_compile_call("plecs.analyze", ["m", "AC"])
    assert crashguard.is_compile_call("plecs.get", ["m", "Topology"])
    assert crashguard.is_compile_call("plecs.get", ["m", "StateSpaceOrder"])
    assert not crashguard.is_compile_call("plecs.get", ["m", "R"])
    assert not crashguard.is_compile_call("plecs.load", ["m.plecs"])


def test_fingerprint_changes_when_the_file_changes(tmp_path: Path):
    path = tmp_path / "m.plecs"
    path.write_text("a", encoding="utf-8")
    first = crashguard.fingerprint(str(path))
    os.utime(path, (time.time() + 5, time.time() + 5))
    path.write_text("ab", encoding="utf-8")
    assert first and crashguard.fingerprint(str(path)) != first
    assert crashguard.fingerprint(str(tmp_path / "missing.plecs")) is None


def test_disconnect_quarantines_the_model(monkeypatch, tmp_path: Path):
    path = tmp_path / "bad.plecs"
    path.write_text("model", encoding="utf-8")
    STATE.loaded("bad", str(path))
    monkeypatch.setattr(server, "_try_restart_plecs", lambda: True)
    monkeypatch.setattr(crashguard, "latest_dump", lambda seconds=180.0: "/tmp/x.dmp")
    try:
        note = server._handle_disconnect(
            "plecs.simulate", ["bad", {}], "Server disconnected without sending a response."
        )
        assert "[plecs-crash]" in note
        assert "/tmp/x.dmp" in note
        assert "quarantined" in note
        record = STATE.crash_for(crashguard.fingerprint(str(path)))
        assert record is not None and record.method == "plecs.simulate"

        with pytest.raises(Exception) as excinfo:
            server._guard_quarantine("bad", "plecs_simulate")
        assert "refused" in str(excinfo.value)

        # editing the file releases the quarantine
        path.write_text("model fixed", encoding="utf-8")
        os.utime(path, (time.time() + 10, time.time() + 10))
        server._guard_quarantine("bad", "plecs_simulate")
    finally:
        STATE.closed("bad")


def test_non_compile_disconnect_is_not_quarantined(monkeypatch, tmp_path: Path):
    path = tmp_path / "ok.plecs"
    path.write_text("model", encoding="utf-8")
    STATE.loaded("ok", str(path))
    try:
        note = server._handle_disconnect("plecs.load", ["ok"], "Server disconnected without sending a response.")
        assert note == ""
        assert STATE.crash_for(crashguard.fingerprint(str(path))) is None
    finally:
        STATE.closed("ok")

import socket
import sys
from pathlib import Path

import pytest

from plecs_mcp import launcher


def _make_app(root: Path, name: str) -> Path:
    app = root / name
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/MacOS/PLECS").write_text("", encoding="utf-8")
    return app


def test_find_app_picks_newest_version(monkeypatch, tmp_path: Path):
    _make_app(tmp_path, "PLECS 4.9.app")
    newest = _make_app(tmp_path, "PLECS 5.0.app")
    monkeypatch.delenv("PLECS_APP_PATH", raising=False)
    monkeypatch.setattr(launcher, "SEARCH_ROOTS", (tmp_path,))
    assert launcher.find_plecs_app() == newest


def test_find_app_prefers_explicit_path(monkeypatch, tmp_path: Path):
    older = _make_app(tmp_path, "PLECS 4.9.app")
    _make_app(tmp_path, "PLECS 5.0.app")
    monkeypatch.setattr(launcher, "SEARCH_ROOTS", (tmp_path,))
    assert launcher.find_plecs_app(str(older)) == older


def test_find_app_returns_none_without_bundles(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PLECS_APP_PATH", raising=False)
    monkeypatch.setattr(launcher, "SEARCH_ROOTS", (tmp_path / "empty",))
    assert launcher.find_plecs_app() is None


def test_launch_uses_open_on_macos(monkeypatch, tmp_path: Path):
    app = _make_app(tmp_path, "PLECS 5.0.app")
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return None

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    result = launcher.launch_plecs(app)
    assert result["ok"] is True
    assert calls["command"] == ["open", "-a", str(app)]
    assert calls["kwargs"]["timeout"] == 30


def test_launch_is_unsupported_off_macos(monkeypatch, tmp_path: Path):
    app = _make_app(tmp_path, "PLECS 5.0.app")
    monkeypatch.setattr(sys, "platform", "linux")
    result = launcher.launch_plecs(app)
    assert result["ok"] is False
    assert "macOS" in result["error"]


def test_wait_for_port_detects_listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        elapsed = launcher.wait_for_port("127.0.0.1", port, timeout=1.0)
    finally:
        server.close()
    assert elapsed is not None


def test_wait_for_port_times_out():
    assert launcher.wait_for_port("127.0.0.1", 1, timeout=0.2, interval=0.05) is None

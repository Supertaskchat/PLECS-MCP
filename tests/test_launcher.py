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


def _make_binary(root: Path, name: str) -> Path:
    binary = root / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch):
    for name in ("PLECS_EXECUTABLE", "PLECS_APP_PATH"):
        monkeypatch.delenv(name, raising=False)


def test_find_app_picks_newest_version(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "darwin")
    _make_app(tmp_path, "PLECS 4.9.app")
    newest = _make_app(tmp_path, "PLECS 5.0.app")
    monkeypatch.setattr(launcher, "MAC_ROOTS", (tmp_path,))
    assert launcher.find_plecs_app() == newest


def test_find_app_prefers_explicit_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "darwin")
    older = _make_app(tmp_path, "PLECS 4.9.app")
    _make_app(tmp_path, "PLECS 5.0.app")
    monkeypatch.setattr(launcher, "MAC_ROOTS", (tmp_path,))
    assert launcher.find_plecs_app(str(older)) == older


def test_find_app_returns_none_without_bundles(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launcher, "MAC_ROOTS", (tmp_path / "empty",))
    assert launcher.find_plecs_app() is None


def test_find_app_windows_executable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "win32")
    binary = _make_binary(tmp_path, "Plexim/PLECS 5.0/plecs.exe")
    monkeypatch.setattr(launcher, "windows_roots", lambda: [tmp_path])
    assert launcher.find_plecs_app() == binary


def test_find_app_linux_binary(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "linux")
    binary = _make_binary(tmp_path, "plecs5/plecs")
    monkeypatch.setattr(launcher, "LINUX_ROOTS", (tmp_path,))
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: None)
    assert launcher.find_plecs_app() == binary


def test_find_app_linux_prefers_which(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "linux")
    binary = _make_binary(tmp_path, "bin/plecs")
    monkeypatch.setattr(launcher, "LINUX_ROOTS", (tmp_path / "empty",))
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: str(binary))
    assert launcher.find_plecs_app() == binary


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


def test_launch_spawns_binary_on_windows_and_linux(monkeypatch, tmp_path: Path):
    binary = _make_binary(tmp_path, "plecs")
    calls = {}

    def fake_popen(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return None

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    for platform in ("win32", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        result = launcher.launch_plecs(binary)
        assert result["ok"] is True
        assert calls["command"] == [str(binary)]
        assert calls["kwargs"]["close_fds"] is True


def test_launch_rejects_unknown_platform(monkeypatch, tmp_path: Path):
    binary = _make_binary(tmp_path, "plecs")
    monkeypatch.setattr(sys, "platform", "freebsd")
    result = launcher.launch_plecs(binary)
    assert result["ok"] is False
    assert "freebsd" in result["error"]


def test_plecs_running_uses_tasklist_on_windows(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        class Result:
            returncode = 0
            stdout = "plecs.exe  1234 Console"
        return Result()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    assert launcher.plecs_running() is True
    assert "tasklist" in seen["command"][0]


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

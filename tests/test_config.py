from pathlib import Path

from plecs_mcp.config import load_config


def test_env_overrides_win(monkeypatch):
    monkeypatch.setenv("PLECS_RPC_HOST", "10.0.0.9")
    monkeypatch.setenv("PLECS_RPC_PORT", "1200")
    monkeypatch.setenv("PLECS_RPC_TIMEOUT", "5")
    cfg = load_config()
    assert (cfg.host, cfg.port, cfg.timeout) == ("10.0.0.9", 1200, 5.0)
    assert cfg.source == "environment"


def test_yaml_file_is_loaded(monkeypatch, tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text('plecs:\n  host: "192.168.1.5"\n  port: 1500\n  timeout: 12\n', encoding="utf-8")
    monkeypatch.setenv("PLECS_MCP_CONFIG", str(path))
    for name in ("PLECS_RPC_HOST", "PLECS_RPC_PORT", "PLECS_RPC_TIMEOUT", "PLECS_HOST", "PLECS_PORT"):
        monkeypatch.delenv(name, raising=False)
    cfg = load_config()
    assert (cfg.host, cfg.port, cfg.timeout) == ("192.168.1.5", 1500, 12.0)
    assert cfg.source == str(path)


def test_legacy_env_names_still_work(monkeypatch):
    monkeypatch.delenv("PLECS_RPC_PORT", raising=False)
    monkeypatch.setenv("PLECS_PORT", "1999")
    assert load_config().port == 1999

import base64
import json

import pytest

from plecs_mcp.codec import (
    PlecsPayloadError,
    base64_to_text,
    decode_model_tree,
    summarize_tree,
    write_bytes,
)


def test_decode_model_tree_roundtrip():
    tree = {"name": "m", "type": "Circuit", "kind": "circuit", "children": []}
    raw = base64.b64encode(json.dumps(tree).encode()).decode()
    assert decode_model_tree(raw) == tree
    assert decode_model_tree(tree) == tree


def test_decode_model_tree_rejects_garbage():
    with pytest.raises(PlecsPayloadError):
        decode_model_tree(base64.b64encode(b"not json").decode())


def test_summarize_tree_collects_names():
    tree = {
        "name": "mdl",
        "type": "Circuit",
        "kind": "circuit",
        "children": [
            {
                "kind": "analysis",
                "type": "AC Sweep",
                "name": "AC Sweep",
                "children": [{"kind": "property", "name": "Name", "value": "Loop Gain (AC Sweep)"}],
            },
            {"kind": "component", "type": "Scope", "name": "Scope", "children": []},
            {"kind": "subsystem", "type": "Subsystem", "name": "PID", "children": []},
            {"kind": "connection", "type": "Connection", "name": "Connection 1", "children": []},
            {"kind": "parameter", "type": "Parameter", "name": "TimeSpan", "children": []},
        ],
    }
    summary = summarize_tree(tree)
    assert summary["analyses"][0]["name"] == "Loop Gain (AC Sweep)"
    assert summary["scopes"] == ["mdl/Scope"]
    assert summary["subsystems"][0]["path"] == "mdl/PID"
    assert "TimeSpan" in summary["parameters"]
    assert "connection" not in summary["counts"]


def test_base64_to_text_rejects_non_base64():
    with pytest.raises(PlecsPayloadError):
        base64_to_text("!!!not-base64!!!")


def test_write_bytes_refuses_overwrite(tmp_path):
    target = tmp_path / "out.csv"
    assert write_bytes(str(target), b"a")["bytes"] == 1
    with pytest.raises(PlecsPayloadError):
        write_bytes(str(target), b"b")
    assert write_bytes(str(target), b"c", overwrite=True)["bytes"] == 1
    assert target.read_bytes() == b"c"

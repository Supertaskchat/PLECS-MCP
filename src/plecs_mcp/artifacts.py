"""Inspect code-generation output and FMU packages."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


def list_artifacts(directory: str | Path, pattern: str = "*", limit: int = 500) -> dict[str, Any]:
    root = Path(directory).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    files = [path for path in root.rglob(pattern) if path.is_file()][:limit]
    entries = [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "modified": int(path.stat().st_mtime),
        }
        for path in files
    ]
    total = sum(entry["bytes"] for entry in entries)
    return {"directory": str(root), "count": len(entries), "bytes": total, "files": entries}


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_model_description(xml_bytes: bytes, source: str) -> dict[str, Any]:
    root = ET.fromstring(xml_bytes)
    fmi_version = root.attrib.get("fmiVersion")
    model_name = root.attrib.get("modelName")
    guid = root.attrib.get("guid")

    variables: list[str] = []
    interfaces: list[str] = []
    for element in root.iter():
        tag = _strip_ns(element.tag)
        if tag == "ScalarVariable":
            variables.append(element.attrib.get("name", ""))
        elif tag in ("ModelExchange", "CoSimulation"):
            interfaces.append(tag)

    return {
        "source": source,
        "fmi_version": fmi_version,
        "model_name": model_name,
        "guid": guid,
        "interfaces": interfaces,
        "variable_count": len(variables),
        "variables_sample": variables[:20],
    }


def fmu_info(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_dir():
        description = target / "modelDescription.xml"
        if not description.is_file():
            raise FileNotFoundError(str(description))
        return _parse_model_description(description.read_bytes(), str(description))
    if not target.is_file():
        raise FileNotFoundError(str(target))
    with zipfile.ZipFile(target) as archive:
        names = [name for name in archive.namelist() if name.endswith("modelDescription.xml")]
        if not names:
            raise ValueError(f"no modelDescription.xml inside {target}")
        return _parse_model_description(archive.read(names[0]), f"{target}!{names[0]}")

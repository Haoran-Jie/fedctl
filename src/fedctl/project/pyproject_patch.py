from __future__ import annotations

import os
from pathlib import Path

import tomlkit


def patch_remote_deployment(
    path: Path,
    *,
    address: str,
    insecure: bool = True,
    backup: bool = True,
) -> Path:
    pyproject_path = _resolve_pyproject(path)
    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))

    tool = _ensure_table(doc, "tool")
    flwr = _ensure_table(tool, "flwr")
    federations = _ensure_table(flwr, "federations")
    remote = _ensure_table(federations, "remote-deployment")
    remote["address"] = address
    remote["insecure"] = bool(insecure)

    payload = tomlkit.dumps(doc)
    _write_toml(pyproject_path, payload, backup=backup)
    return pyproject_path


def _resolve_pyproject(path: Path) -> Path:
    if path.is_dir():
        pyproject_path = path / "pyproject.toml"
    else:
        pyproject_path = path
    if pyproject_path.name != "pyproject.toml":
        raise ValueError(f"Expected pyproject.toml, got {pyproject_path}.")
    if not pyproject_path.exists():
        raise FileNotFoundError(f"No pyproject.toml found at {pyproject_path}.")
    return pyproject_path


def _ensure_table(parent, key: str):
    if key not in parent or not isinstance(parent[key], tomlkit.items.Table):
        parent[key] = tomlkit.table()
    return parent[key]


def _write_toml(path: Path, payload: str, *, backup: bool) -> None:
    if backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)

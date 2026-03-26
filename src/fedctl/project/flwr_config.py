from __future__ import annotations

import os
from pathlib import Path

import tomlkit


def resolve_flwr_home(*, project_root: Path, flwr_home: str | Path | None = None) -> Path:
    if flwr_home is not None:
        return Path(flwr_home).expanduser().resolve()

    env_home = os.environ.get("FLWR_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    return (project_root / ".fedctl" / "flwr").resolve()


def write_superlink_connection(
    *,
    flwr_home: Path,
    name: str,
    address: str,
    insecure: bool = True,
    backup: bool = True,
    default_connection: str | None = None,
) -> Path:
    cfg_path = flwr_home / "config.toml"
    flwr_home.mkdir(parents=True, exist_ok=True)

    if cfg_path.exists():
        doc = tomlkit.parse(cfg_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    superlink = _ensure_table(doc, "superlink")
    if default_connection:
        superlink["default"] = default_connection

    connection = _ensure_table(superlink, name)
    connection["address"] = address
    connection["insecure"] = bool(insecure)

    payload = tomlkit.dumps(doc)
    _write_toml(cfg_path, payload, backup=backup)
    return cfg_path


def _ensure_table(parent, key: str):
    if key not in parent or not isinstance(parent[key], tomlkit.items.Table):
        parent[key] = tomlkit.table()
    return parent[key]


def _write_toml(path: Path, payload: str, *, backup: bool) -> None:
    if backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)

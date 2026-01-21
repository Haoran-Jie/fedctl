from __future__ import annotations

from pathlib import Path
from typing import Dict

import tomlkit

from .paths import config_path
from .schema import FedctlConfig, ProfileConfig, TailscaleConfig


def ensure_config_exists() -> Path:
    cfg_path = config_path()
    cfg_dir = cfg_path.parent
    cfg_dir.mkdir(parents=True, exist_ok=True)

    if not cfg_path.exists():
        doc = tomlkit.document()
        doc["active_profile"] = "default"

        profiles = tomlkit.table()
        doc["profiles"] = profiles

        default_tbl = tomlkit.table()
        default_tbl["endpoint"] = "http://127.0.0.1:4646"
        default_tbl["tls_skip_verify"] = False
        default_tbl["access_mode"] = "lan-only"

        # Optional nested section can exist but should not contain None
        ts = tomlkit.table()
        default_tbl["tailscale"] = ts

        profiles["default"] = default_tbl
        cfg_path.write_text(tomlkit.dumps(doc))

    return cfg_path



def load_raw_toml() -> tomlkit.TOMLDocument:
    path = ensure_config_exists()
    return tomlkit.parse(path.read_text())


def save_raw_toml(doc: tomlkit.TOMLDocument) -> None:
    path = ensure_config_exists()
    path.write_text(tomlkit.dumps(doc))


def load_config() -> FedctlConfig:
    doc = load_raw_toml()
    active = str(doc.get("active_profile", "default"))
    profiles_tbl = doc.get("profiles", {})

    profiles: Dict[str, ProfileConfig] = {}
    for name, p in profiles_tbl.items():
        ts_tbl = p.get("tailscale", {}) if hasattr(p, "get") else {}
        tailscale = TailscaleConfig(subnet_cidr=ts_tbl.get("subnet_cidr"))
        profiles[name] = ProfileConfig(
            endpoint=str(p["endpoint"]),
            namespace=p.get("namespace"),
            repo_config=p.get("repo_config"),
            tls_ca=p.get("tls_ca"),
            tls_skip_verify=bool(p.get("tls_skip_verify", False)),
            access_mode=p.get("access_mode", "lan-only"),
            tailscale=tailscale,
        )

    return FedctlConfig(active_profile=active, profiles=profiles)

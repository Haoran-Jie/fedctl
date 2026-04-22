from __future__ import annotations

from pathlib import Path
from typing import Dict

import tomlkit

from .paths import config_path, repo_default_config_path
from .schema import FedctlConfig, ProfileConfig

_DEFAULT_REPO_CONFIG_TEXT = """# Default fedctl repo config.
# Project-local .fedctl/fedctl.yaml takes precedence over this file.
# Fill placeholders before production use.

deploy:
  supernodes:
    rpi5: 2
    jetson: 2
  superexec:
    # Optional env vars injected into SuperExec server/client containers.
    # Use this for remote experiment auth/config such as W&B.
    env: {}
    # Example:
    # env:
    #   WANDB_PROJECT: "fedctl"
    #   WANDB_ENTITY: "your-wandb-entity"
    #   WANDB_API_KEY: "set-a-real-key-here"
  placement:
    allow_oversubscribe: true
    spread_across_hosts: true
  resources:
    supernode:
      default: { cpu: 500, mem: 512 }
      rpi5: { cpu: 500, mem: 512 }
      jetson: { cpu: 1000, mem: 1024 }
  network:
    image: "jiahborcn/netem:latest"
    default_profile: none
    # Optional fallback used when CLI --net is absent.
    # Example: default_assignment: "rpi5[*]=med,jetson[*]=high"
    interface: eth0
    apply:
      superexec_serverapp: false
      superexec_clientapp: false
    profiles:
      none: {}
      low: { delay_ms: 0, jitter_ms: 0, loss_pct: 0 }
      med: { delay_ms: 60, jitter_ms: 10, loss_pct: 1.0, rate_mbit: 50, rate_latency_ms: 50, rate_burst_kbit: 256 }
      high: { delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }

submit:
  image: "100.82.158.122:5000/fedctl-submit:latest"
  artifact_store: "s3+presign://fedctl-submits/fedctl-submits"
  endpoint: "http://100.82.158.122:8080"
  token: "flwruser1"
  user: "DEFAULT_USER"

submit-service:
  endpoint: "http://127.0.0.1:8080"
  nomad_endpoint: "http://128.232.61.111:4646"
  dispatch_mode: "queue"
  image_registry: "128.232.61.111:5000"

image_registry: "100.82.158.122:5000"
"""


def ensure_config_exists() -> Path:
    cfg_path = config_path()
    cfg_dir = cfg_path.parent
    cfg_dir.mkdir(parents=True, exist_ok=True)
    default_repo_cfg = _ensure_default_repo_config_exists()

    if not cfg_path.exists():
        doc = tomlkit.document()
        doc["active_profile"] = "default"

        profiles = tomlkit.table()
        doc["profiles"] = profiles

        default_tbl = tomlkit.table()
        default_tbl["endpoint"] = "http://127.0.0.1:4646"
        default_tbl["repo_config"] = str(default_repo_cfg)

        profiles["default"] = default_tbl
        cfg_path.write_text(tomlkit.dumps(doc))
    else:
        doc = tomlkit.parse(cfg_path.read_text())
        profiles = doc.get("profiles")
        if isinstance(profiles, dict):
            default_tbl = profiles.get("default")
            if isinstance(default_tbl, dict):
                repo_cfg = default_tbl.get("repo_config")
                if not isinstance(repo_cfg, str) or not repo_cfg.strip():
                    default_tbl["repo_config"] = str(default_repo_cfg)
                    cfg_path.write_text(tomlkit.dumps(doc))

    return cfg_path


def _ensure_default_repo_config_exists() -> Path:
    path = repo_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_DEFAULT_REPO_CONFIG_TEXT, encoding="utf-8")
    return path



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
        profiles[name] = ProfileConfig(
            endpoint=str(p["endpoint"]),
            namespace=p.get("namespace"),
            repo_config=p.get("repo_config"),
        )

    return FedctlConfig(active_profile=active, profiles=profiles)

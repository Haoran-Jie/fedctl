from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Dict

import tomlkit

from .paths import config_path, deploy_default_config_path
from .schema import FedctlConfig, ProfileConfig

DEFAULT_NOMAD_ENDPOINT = "http://128.232.61.111:4646"
DEFAULT_SUBMIT_ENDPOINT = "http://fedctl.cl.cam.ac.uk"
DEFAULT_IMAGE_REGISTRY = "128.232.61.111:5000"
DEFAULT_SUBMIT_IMAGE = f"{DEFAULT_IMAGE_REGISTRY}/fedctl-submit:latest"
DEFAULT_ARTIFACT_STORE = "s3+presign://fedctl-submits/fedctl-submits"
DEFAULT_NETEM_IMAGE = "jiahborcn/netem:latest"


def _default_deploy_config_text() -> str:
    submit_user = _default_submit_user()
    return f"""# Default fedctl deploy config for the CamMLSys cluster.
# Project-local .fedctl/fedctl.yaml takes precedence over this file.
# Fresh installs only need a submit-service bearer token:
#   submit.token: "<your-token>"
# You can also leave this file untouched and export FEDCTL_SUBMIT_TOKEN.

deploy:
  superexec:
    # Optional env vars injected into SuperExec server/client containers.
    # Use this for remote experiment auth/config such as W&B.
    env: {{}}
    # Example:
    # env:
    #   WANDB_PROJECT: "fedctl"
    #   WANDB_ENTITY: "your-wandb-entity"
    #   WANDB_API_KEY: "set-a-real-key-here"
  # Advanced overrides. Leave these commented for normal CamMLSys use;
  # fedctl supplies the shared defaults in code.
  # image_registry: "{DEFAULT_IMAGE_REGISTRY}"
  # supernodes:
  #   rpi4: 2
  #   rpi5: 2
  # placement:
  #   allow_oversubscribe: true
  #   spread_across_hosts: true
  #   prefer_spread_across_hosts: true
  # resources:
  #   supernode:
  #     default: {{ cpu: 1000, mem: 1024 }}
  #     rpi4: {{ cpu: 1000, mem: 1024 }}
  #     rpi5: {{ cpu: 1000, mem: 1024 }}
  #   superexec_clientapp: {{ cpu: 2000, mem: 2048 }}
  #   superexec_serverapp: {{ cpu: 2000, mem: 2048 }}
  #   superlink: {{ cpu: 1000, mem: 1024 }}
  # network:
  #   image: "{DEFAULT_NETEM_IMAGE}"
  #   default_profile: none
  #   # Optional fallback used when CLI --net is absent.
  #   # default_assignment can be a string or a list of strings.
  #   # default_assignment: "rpi5[*]=med,rpi4[*]=high"
  #   interface: eth0
  #   apply:
  #     superexec_serverapp: false
  #     superexec_clientapp: false
  #   profiles:
  #     none: {{}}
  #     low: {{ delay_ms: 0, jitter_ms: 0, loss_pct: 0, rate_mbit: 1000, rate_latency_ms: 0, rate_burst_kbit: 256 }}
  #     med: {{ delay_ms: 60, jitter_ms: 10, loss_pct: 1.0, rate_mbit: 50, rate_latency_ms: 50, rate_burst_kbit: 256 }}
  #     high: {{ delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }}
  #   # Optional direction-specific overrides.
  #   ingress_profiles:
  #     slow_downlink: {{ delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }}
  #   egress_profiles:
  #     slow_uplink: {{ delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }}

submit:
  token: ""
  user: "{submit_user}"
  # Advanced overrides. Leave these commented for normal CamMLSys use.
  # endpoint: "{DEFAULT_SUBMIT_ENDPOINT}"
  # image: "{DEFAULT_SUBMIT_IMAGE}"
  # artifact_store: "{DEFAULT_ARTIFACT_STORE}"
"""


def _default_submit_user() -> str:
    for env_name in ("FEDCTL_SUBMIT_USER", "USER", "LOGNAME", "USERNAME"):
        value = os.environ.get(env_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        value = getpass.getuser()
    except Exception:
        value = ""
    return value.strip() or "cammlsys-user"


def ensure_config_exists() -> Path:
    cfg_path = config_path()
    cfg_dir = cfg_path.parent
    cfg_dir.mkdir(parents=True, exist_ok=True)
    default_deploy_cfg = _ensure_default_deploy_config_exists()

    if not cfg_path.exists():
        doc = tomlkit.document()
        doc["active_profile"] = "default"

        profiles = tomlkit.table()
        doc["profiles"] = profiles

        default_tbl = tomlkit.table()
        default_tbl["endpoint"] = DEFAULT_NOMAD_ENDPOINT
        default_tbl["namespace"] = "default"
        default_tbl["deploy_config"] = str(default_deploy_cfg)

        profiles["default"] = default_tbl
        cfg_path.write_text(tomlkit.dumps(doc))
    else:
        doc = tomlkit.parse(cfg_path.read_text())
        profiles = doc.get("profiles")
        if isinstance(profiles, dict):
            changed = False
            for name, profile_tbl in profiles.items():
                if not isinstance(profile_tbl, dict):
                    continue
                if _migrate_profile_deploy_config_key(profile_tbl):
                    changed = True
                if name == "default":
                    deploy_cfg = profile_tbl.get("deploy_config")
                    if not isinstance(deploy_cfg, str) or not deploy_cfg.strip():
                        profile_tbl["deploy_config"] = str(default_deploy_cfg)
                        changed = True
            if changed:
                cfg_path.write_text(tomlkit.dumps(doc))

    return cfg_path


def _ensure_default_deploy_config_exists() -> Path:
    path = deploy_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_default_deploy_config_text(), encoding="utf-8")
    return path


def _migrate_profile_deploy_config_key(profile_tbl: dict[str, object]) -> bool:
    deploy_cfg = profile_tbl.get("deploy_config")
    if isinstance(deploy_cfg, str) and deploy_cfg.strip():
        if "repo_config" in profile_tbl:
            profile_tbl.pop("repo_config", None)
            return True
        return False

    legacy_deploy_cfg = profile_tbl.get("repo_config")
    if isinstance(legacy_deploy_cfg, str) and legacy_deploy_cfg.strip():
        profile_tbl["deploy_config"] = legacy_deploy_cfg
        profile_tbl.pop("repo_config", None)
        return True
    return False


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
        deploy_config = p.get("deploy_config") or p.get("repo_config")
        profiles[name] = ProfileConfig(
            endpoint=str(p["endpoint"]),
            namespace=p.get("namespace"),
            deploy_config=deploy_config,
        )

    return FedctlConfig(active_profile=active, profiles=profiles)

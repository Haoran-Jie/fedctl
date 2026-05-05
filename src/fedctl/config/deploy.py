from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from .io import (
    DEFAULT_ARTIFACT_STORE,
    DEFAULT_IMAGE_REGISTRY,
    DEFAULT_NETEM_IMAGE,
    DEFAULT_SUBMIT_ENDPOINT,
    DEFAULT_SUBMIT_IMAGE,
)


def load_deploy_config(
    base: Path | None = None, config_path: Path | None = None
) -> dict[str, Any]:
    if config_path:
        path = config_path
        if not path.is_absolute():
            path = (base or Path.cwd()) / path
    else:
        path = _find_deploy_config(base or Path.cwd())
    if not path:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class ResolvedDeployConfig:
    path: Path | None
    data: dict[str, Any]


def resolve_deploy_config(
    *,
    deploy_config: str | Path | None = None,
    project_root: Path | None = None,
    profile_name: str | None = None,
    include_project_local: bool = False,
    include_profile: bool = False,
) -> ResolvedDeployConfig:
    path = resolve_deploy_config_path(
        deploy_config=deploy_config,
        project_root=project_root,
        profile_name=profile_name,
        include_project_local=include_project_local,
        include_profile=include_profile,
    )
    data = load_deploy_config(config_path=path) if path else {}
    return ResolvedDeployConfig(path=path, data=data)


def resolve_deploy_config_path(
    *,
    deploy_config: str | Path | None = None,
    project_root: Path | None = None,
    profile_name: str | None = None,
    include_project_local: bool = False,
    include_profile: bool = False,
) -> Path | None:
    explicit = _normalize_path(deploy_config)
    if explicit is not None:
        return explicit if explicit.exists() else None

    if include_project_local and project_root is not None:
        candidate = _find_deploy_config(project_root)
        if candidate is not None:
            return candidate

    if include_profile:
        candidate = _profile_deploy_config_path(profile_name=profile_name)
        if candidate is not None:
            return candidate

    return None


@dataclass(frozen=True)
class SubmitDeployConfig:
    image: str | None = None
    artifact_store: str | None = None
    endpoint: str | None = None
    token: str | None = None
    user: str | None = None


@dataclass(frozen=True)
class EffectiveDeployConfig:
    supernodes: dict[str, object]
    supernode_resources: dict[str, object]
    superexec_clientapp_resources: dict[str, object]
    superexec_serverapp_resources: dict[str, object]
    superlink_resources: dict[str, object]
    superexec_env: dict[str, str]
    network_profiles: dict[str, object]
    network_ingress_profiles: dict[str, object]
    network_egress_profiles: dict[str, object]
    network_default: str | None
    network_default_assignment: list[str] | None
    network_interface: str | None
    network_image: str | None
    network_apply: dict[str, object]
    allow_oversubscribe: bool
    spread_across_hosts: bool
    prefer_spread_across_hosts: bool


def parse_submit_deploy_config(deploy_cfg: dict[str, Any]) -> SubmitDeployConfig:
    submit = deploy_cfg.get("submit", {}) if isinstance(deploy_cfg.get("submit"), dict) else {}
    image = submit.get("image")
    artifact_store = submit.get("artifact_store")
    endpoint = submit.get("endpoint")
    token = submit.get("token")
    user = submit.get("user")
    return SubmitDeployConfig(
        image=str(image) if isinstance(image, str) and image else DEFAULT_SUBMIT_IMAGE,
        artifact_store=(
            str(artifact_store)
            if isinstance(artifact_store, str) and artifact_store
            else DEFAULT_ARTIFACT_STORE
        ),
        endpoint=str(endpoint) if isinstance(endpoint, str) and endpoint else DEFAULT_SUBMIT_ENDPOINT,
        token=str(token) if isinstance(token, str) and token else None,
        user=str(user) if isinstance(user, str) and user else None,
    )


def resolve_effective_deploy_config(deploy_cfg: dict[str, Any]) -> EffectiveDeployConfig:
    deploy = _as_dict(deploy_cfg.get("deploy"))
    supernodes = _as_positive_int_dict(_as_dict(deploy.get("supernodes")))
    placement = _as_dict(deploy.get("placement"))
    resources = _as_dict(deploy.get("resources"))
    superexec = _as_dict(deploy.get("superexec"))
    superexec_env = _as_string_dict(_as_dict(superexec.get("env")))
    supernode_resources = _as_dict(resources.get("supernode")) or {
        "default": {"cpu": 1000, "mem": 1024},
        "rpi4": {"cpu": 1000, "mem": 1024},
        "rpi5": {"cpu": 1000, "mem": 1024},
    }
    superexec_clientapp_resources = _as_dict(resources.get("superexec_clientapp")) or {
        "cpu": 2000,
        "mem": 2048,
    }
    superexec_serverapp_resources = _as_dict(resources.get("superexec_serverapp")) or {
        "cpu": 2000,
        "mem": 2048,
    }
    superlink_resources = _as_dict(resources.get("superlink")) or {
        "cpu": 1000,
        "mem": 1024,
    }
    network = _as_dict(deploy.get("network"))
    network_profiles = _as_dict(network.get("profiles")) or {
        "none": {},
        "low": {
            "delay_ms": 0,
            "jitter_ms": 0,
            "loss_pct": 0,
            "rate_mbit": 1000,
            "rate_latency_ms": 0,
            "rate_burst_kbit": 256,
        },
        "med": {
            "delay_ms": 60,
            "jitter_ms": 10,
            "loss_pct": 1.0,
            "rate_mbit": 50,
            "rate_latency_ms": 50,
            "rate_burst_kbit": 256,
        },
        "high": {
            "delay_ms": 120,
            "jitter_ms": 25,
            "loss_pct": 2.5,
            "rate_mbit": 20,
            "rate_latency_ms": 50,
            "rate_burst_kbit": 256,
        },
    }
    network_ingress_profiles = _as_dict(network.get("ingress_profiles"))
    network_egress_profiles = _as_dict(network.get("egress_profiles"))
    network_apply = {
        "superexec_serverapp": False,
        "superexec_clientapp": False,
        **_as_dict(network.get("apply")),
    }
    return EffectiveDeployConfig(
        supernodes=supernodes,
        supernode_resources=supernode_resources,
        superexec_clientapp_resources=superexec_clientapp_resources,
        superexec_serverapp_resources=superexec_serverapp_resources,
        superlink_resources=superlink_resources,
        superexec_env=superexec_env,
        network_profiles=network_profiles,
        network_ingress_profiles=network_ingress_profiles,
        network_egress_profiles=network_egress_profiles,
        network_default=_as_optional_str(network.get("default_profile")) or "none",
        network_default_assignment=_as_optional_str_list(network.get("default_assignment")),
        network_interface=_as_optional_str(network.get("interface")) or "eth0",
        network_image=_as_optional_str(network.get("image")) or DEFAULT_NETEM_IMAGE,
        network_apply=network_apply,
        allow_oversubscribe=_as_bool(placement.get("allow_oversubscribe"), default=True),
        spread_across_hosts=_as_bool(placement.get("spread_across_hosts"), default=True),
        prefer_spread_across_hosts=_as_bool(
            placement.get("prefer_spread_across_hosts"), default=True
        ),
    )


def get_image_registry(deploy_cfg: dict[str, Any]) -> str | None:
    deploy = deploy_cfg.get("deploy")
    if isinstance(deploy, dict):
        value = deploy.get("image_registry")
        if isinstance(value, str) and value.strip():
            return _normalize_registry(value)

    # Legacy deploy configs stored the user-visible registry at the top level.
    value = deploy_cfg.get("image_registry")
    if isinstance(value, str) and value.strip():
        return _normalize_registry(value)

    # Older build-specific configs may still provide this fallback.
    build_cfg = deploy_cfg.get("build", {})
    if isinstance(build_cfg, dict):
        value = build_cfg.get("image_registry")
        if isinstance(value, str) and value.strip():
            return _normalize_registry(value)
    return DEFAULT_IMAGE_REGISTRY


def get_cluster_image_registry(deploy_cfg: dict[str, Any]) -> str | None:
    # Legacy split-registry configs used this as a cluster-visible registry
    # override. New deploy configs should use deploy.image_registry only.
    submit_service_cfg = deploy_cfg.get("submit-service", {})
    if isinstance(submit_service_cfg, dict):
        value = submit_service_cfg.get("image_registry")
        if isinstance(value, str) and value.strip():
            return _normalize_registry(value)
    return get_image_registry(deploy_cfg)


def get_deploy_config_label(deploy_cfg: dict[str, Any], *, path: Path | None = None) -> str:
    network_label = get_deploy_network_profile_label(deploy_cfg)
    if network_label:
        return network_label
    if path is not None:
        return path.stem.replace("_", "-") or "default"
    return "default"


def get_deploy_network_profile_label(deploy_cfg: dict[str, Any]) -> str | None:
    deploy = deploy_cfg.get("deploy")
    if not isinstance(deploy, dict):
        return None
    network = deploy.get("network")
    if not isinstance(network, dict):
        return None
    value = network.get("default_profile")
    if not isinstance(value, str):
        return None
    label = value.strip().replace("_", "-")
    return label or None


def rewrite_image_registry(
    image: str,
    *,
    source_registry: str | None = None,
    target_registry: str | None = None,
) -> str:
    image = image.strip()
    target = _normalize_registry(target_registry)
    if not image or not target:
        return image

    current_registry, remainder = _split_image_reference(image)
    if current_registry is None:
        return image
    if current_registry == target:
        return image

    source = _normalize_registry(source_registry)
    if source and current_registry != source:
        return image

    return f"{target}/{remainder}"


def _normalize_registry(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _split_image_reference(image: str) -> tuple[str | None, str]:
    first, sep, remainder = image.partition("/")
    if not sep:
        return None, image
    if "." in first or ":" in first or first == "localhost":
        return first, remainder
    return None


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _as_optional_str_list(value: object) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or None
    return None


def _as_string_dict(value: dict[str, object]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            continue
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            resolved[key] = text
    return resolved


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_positive_int_dict(value: dict[str, object]) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for key, raw in value.items():
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        if count > 0:
            resolved[str(key)] = count
    return resolved


def _find_deploy_config(base: Path) -> Path | None:
    base = base.resolve()
    if base.is_file():
        base = base.parent
    candidate = base / ".fedctl" / "fedctl.yaml"
    return candidate if candidate.exists() else None


def _profile_deploy_config_path(*, profile_name: str | None = None) -> Path | None:
    try:
        from .io import load_config
    except Exception:
        return None

    try:
        cfg = load_config()
    except Exception:
        return None

    selected = profile_name or os.environ.get("FEDCTL_PROFILE") or cfg.active_profile
    profile_cfg = cfg.profiles.get(selected)
    if not profile_cfg or not profile_cfg.deploy_config:
        return None

    path = _normalize_path(profile_cfg.deploy_config)
    if path is None or not path.exists():
        return None
    return path


def _normalize_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path

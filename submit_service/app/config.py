from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import yaml


@dataclass(frozen=True)
class SubmitConfig:
    db_url: str
    tokens: set[str]
    allow_unauth: bool
    service_endpoint: str | None
    nomad_endpoint: str | None
    nomad_token: str | None
    nomad_namespace: str | None
    nomad_tls_ca: str | None
    nomad_tls_skip_verify: bool
    dispatch_mode: str
    dispatch_interval: int
    datacenter: str
    default_priority: int
    docker_socket: str | None


def load_config() -> SubmitConfig:
    repo_submit = _repo_submit_config()
    db_url = os.environ.get(
        "SUBMIT_DB_URL", "sqlite:///submit_service/state/submit.db"
    )
    token_raw = os.environ.get("FEDCTL_SUBMIT_TOKENS", "").strip()
    if not token_raw:
        token_raw = str(repo_submit.get("tokens") or "").strip()
    tokens = {t.strip() for t in token_raw.split(",") if t.strip()}
    allow_unauth_env = os.environ.get("FEDCTL_SUBMIT_ALLOW_UNAUTH", "")
    if not allow_unauth_env:
        allow_unauth_env = str(repo_submit.get("allow_unauth") or "")
    allow_unauth_default = _repo_allow_unauth_default()
    allow_unauth = _parse_bool(
        allow_unauth_env,
        default=allow_unauth_default if allow_unauth_default is not None else not tokens,
    )

    service_endpoint = os.environ.get("SUBMIT_SERVICE_ENDPOINT") or repo_submit.get(
        "endpoint"
    )
    nomad_endpoint = os.environ.get("SUBMIT_NOMAD_ENDPOINT") or repo_submit.get(
        "nomad_endpoint"
    )
    nomad_token = os.environ.get("SUBMIT_NOMAD_TOKEN") or repo_submit.get("nomad_token")
    nomad_namespace = os.environ.get("SUBMIT_NOMAD_NAMESPACE") or repo_submit.get(
        "nomad_namespace"
    )
    nomad_tls_ca = os.environ.get("SUBMIT_NOMAD_TLS_CA") or repo_submit.get(
        "nomad_tls_ca"
    )
    nomad_tls_skip_verify = _parse_bool(
        os.environ.get("SUBMIT_NOMAD_TLS_SKIP_VERIFY", ""),
        default=_parse_bool(str(repo_submit.get("nomad_tls_skip_verify") or ""), default=False),
    )

    dispatch_mode = os.environ.get(
        "SUBMIT_DISPATCH_MODE", str(repo_submit.get("dispatch_mode") or "immediate")
    ).strip().lower()
    dispatch_interval = _parse_int(
        os.environ.get("SUBMIT_DISPATCH_INTERVAL", ""),
        default=_parse_int(str(repo_submit.get("dispatch_interval") or ""), default=10),
    )
    datacenter = os.environ.get(
        "SUBMIT_DATACENTER", str(repo_submit.get("datacenter") or "dc1")
    )
    default_priority = _parse_int(
        os.environ.get("SUBMIT_DEFAULT_PRIORITY", ""),
        default=_parse_int(str(repo_submit.get("default_priority") or ""), default=50),
    )

    docker_socket = os.environ.get(
        "SUBMIT_DOCKER_SOCKET", str(repo_submit.get("docker_socket") or "/var/run/docker.sock")
    )
    if docker_socket == "":
        docker_socket = None

    return SubmitConfig(
        db_url=db_url,
        tokens=tokens,
        allow_unauth=allow_unauth,
        service_endpoint=service_endpoint,
        nomad_endpoint=nomad_endpoint,
        nomad_token=nomad_token,
        nomad_namespace=nomad_namespace,
        nomad_tls_ca=nomad_tls_ca,
        nomad_tls_skip_verify=nomad_tls_skip_verify,
        dispatch_mode=dispatch_mode,
        dispatch_interval=dispatch_interval,
        datacenter=datacenter,
        default_priority=default_priority,
        docker_socket=docker_socket,
    )


def ensure_sqlite_path(db_url: str) -> Path | None:
    if not db_url.startswith("sqlite:///"):
        return None
    path = db_url.replace("sqlite:///", "", 1)
    return Path(path)


def _parse_bool(value: str, *, default: bool) -> bool:
    if not value:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _repo_allow_unauth_default() -> bool | None:
    data = _repo_config_data()
    if not data:
        return None
    submit = data.get("submit-service", {})
    if not isinstance(submit, dict):
        return None
    value = submit.get("allow_unauth")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _parse_bool(value, default=False)
    return None


def _repo_submit_config() -> dict[str, object]:
    data = _repo_config_data()
    if not data:
        return {}
    submit = data.get("submit-service", {})
    return submit if isinstance(submit, dict) else {}


def _repo_config_data() -> dict[str, object] | None:
    path_raw = os.environ.get("SUBMIT_REPO_CONFIG", "").strip()
    path = Path(path_raw) if path_raw else Path.cwd() / ".fedctl" / "fedctl.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_int(value: str, *, default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default

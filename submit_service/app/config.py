from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class SubmitConfig:
    db_url: str
    tokens: set[str]
    allow_unauth: bool
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
    db_url = os.environ.get(
        "SUBMIT_DB_URL", "sqlite:///submit_service/state/submit.db"
    )
    token_raw = os.environ.get("FEDCTL_SUBMIT_TOKENS", "").strip()
    tokens = {t.strip() for t in token_raw.split(",") if t.strip()}
    allow_unauth_env = os.environ.get("FEDCTL_SUBMIT_ALLOW_UNAUTH", "")
    allow_unauth = _parse_bool(allow_unauth_env, default=not tokens)

    nomad_endpoint = os.environ.get("SUBMIT_NOMAD_ENDPOINT")
    nomad_token = os.environ.get("SUBMIT_NOMAD_TOKEN")
    nomad_namespace = os.environ.get("SUBMIT_NOMAD_NAMESPACE")
    nomad_tls_ca = os.environ.get("SUBMIT_NOMAD_TLS_CA")
    nomad_tls_skip_verify = _parse_bool(
        os.environ.get("SUBMIT_NOMAD_TLS_SKIP_VERIFY", ""), default=False
    )

    dispatch_mode = os.environ.get("SUBMIT_DISPATCH_MODE", "immediate").strip().lower()
    dispatch_interval = int(os.environ.get("SUBMIT_DISPATCH_INTERVAL", "10"))
    datacenter = os.environ.get("SUBMIT_DATACENTER", "dc1")
    default_priority = int(os.environ.get("SUBMIT_DEFAULT_PRIORITY", "50"))

    docker_socket = os.environ.get("SUBMIT_DOCKER_SOCKET", "/var/run/docker.sock")
    if docker_socket == "":
        docker_socket = None

    return SubmitConfig(
        db_url=db_url,
        tokens=tokens,
        allow_unauth=allow_unauth,
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

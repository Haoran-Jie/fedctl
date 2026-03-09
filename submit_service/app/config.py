from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import json

import yaml


@dataclass(frozen=True)
class TokenIdentity:
    name: str
    role: str


@dataclass(frozen=True)
class SubmitConfig:
    db_url: str
    tokens: set[str]
    token_identities: dict[str, TokenIdentity]
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
    nomad_inventory_ttl: int
    autopurge_completed_after_s: int
    ui_enabled: bool = False
    ui_session_secret: str | None = None
    ui_cookie_name: str = "fedctl_submit_session"
    ui_cookie_secure: bool = False


def load_config() -> SubmitConfig:
    repo_submit = _repo_submit_config()
    db_url = os.environ.get(
        "SUBMIT_DB_URL", "sqlite:///submit_service/state/submit.db"
    )
    token_identities = _resolve_token_identities(repo_submit)
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
        default=allow_unauth_default
        if allow_unauth_default is not None
        else not (tokens or token_identities),
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

    nomad_inventory_ttl = _parse_int(
        os.environ.get("SUBMIT_NOMAD_INV_TTL", ""),
        default=_parse_int(str(repo_submit.get("nomad_inventory_ttl") or ""), default=5),
    )
    autopurge_completed_after_s = _parse_int(
        os.environ.get("SUBMIT_AUTOPURGE_COMPLETED_AFTER", ""),
        default=_parse_int(
            str(repo_submit.get("autopurge_completed_after_s") or ""),
            default=0,
        ),
    )
    ui_enabled = _parse_bool(
        os.environ.get("SUBMIT_UI_ENABLED", ""),
        default=_parse_bool(str(repo_submit.get("ui_enabled") or ""), default=False),
    )
    ui_session_secret_raw = os.environ.get("SUBMIT_UI_SESSION_SECRET")
    if ui_session_secret_raw is None:
        repo_secret = repo_submit.get("ui_session_secret")
        ui_session_secret_raw = repo_secret if isinstance(repo_secret, str) else None
    ui_session_secret = ui_session_secret_raw.strip() if ui_session_secret_raw else None
    ui_cookie_name = (
        os.environ.get("SUBMIT_UI_COOKIE_NAME")
        or str(repo_submit.get("ui_cookie_name") or "fedctl_submit_session")
    ).strip() or "fedctl_submit_session"
    ui_cookie_secure = _parse_bool(
        os.environ.get("SUBMIT_UI_COOKIE_SECURE", ""),
        default=_parse_bool(str(repo_submit.get("ui_cookie_secure") or ""), default=False),
    )

    docker_socket = os.environ.get(
        "SUBMIT_DOCKER_SOCKET", str(repo_submit.get("docker_socket") or "/var/run/docker.sock")
    )
    if docker_socket == "":
        docker_socket = None

    return SubmitConfig(
        db_url=db_url,
        tokens=tokens,
        token_identities=token_identities,
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
        nomad_inventory_ttl=nomad_inventory_ttl,
        autopurge_completed_after_s=max(0, autopurge_completed_after_s),
        ui_enabled=ui_enabled,
        ui_session_secret=ui_session_secret,
        ui_cookie_name=ui_cookie_name,
        ui_cookie_secure=ui_cookie_secure,
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


def _resolve_token_identities(repo_submit: dict[str, object]) -> dict[str, TokenIdentity]:
    env_raw = os.environ.get("FEDCTL_SUBMIT_TOKEN_MAP", "").strip()
    if env_raw:
        return _parse_token_map(env_raw)
    repo_map = repo_submit.get("token_map")
    return _parse_token_map_obj(repo_map)


def _parse_token_map(raw: str) -> dict[str, TokenIdentity]:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_token_map_csv(raw)
    return _parse_token_map_obj(loaded)


def _parse_token_map_obj(value: object) -> dict[str, TokenIdentity]:
    if not isinstance(value, dict):
        return {}
    identities: dict[str, TokenIdentity] = {}
    for token, info in value.items():
        if not isinstance(token, str) or not token.strip():
            continue
        name, role = _token_identity_parts(info)
        if not name:
            continue
        identities[token.strip()] = TokenIdentity(name=name, role=role)
    return identities


def _parse_token_map_csv(raw: str) -> dict[str, TokenIdentity]:
    identities: dict[str, TokenIdentity] = {}
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    for part in parts:
        if "=" not in part:
            continue
        token, info = part.split("=", 1)
        token = token.strip()
        if not token:
            continue
        name, role = _token_identity_parts(info.strip())
        if not name:
            continue
        identities[token] = TokenIdentity(name=name, role=role)
    return identities


def _token_identity_parts(value: object) -> tuple[str | None, str]:
    if isinstance(value, dict):
        name = value.get("name")
        role = value.get("role")
        return _clean_name(name), _normalize_role(role)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, "user"
        if ":" in raw:
            name, role = raw.rsplit(":", 1)
            return _clean_name(name), _normalize_role(role)
        return _clean_name(raw), "user"
    return None, "user"


def _clean_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _normalize_role(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() == "admin":
        return "admin"
    return "user"


def _repo_config_data() -> dict[str, object] | None:
    path_raw = os.environ.get("SUBMIT_REPO_CONFIG", "").strip()
    if path_raw:
        path = Path(path_raw).expanduser()
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    repo_dir = Path.cwd() / ".fedctl"
    for path in (repo_dir / "fedctl_local.yaml", repo_dir / "fedctl.yaml"):
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def load_repo_config_data() -> dict[str, object]:
    data = _repo_config_data()
    return data if data else {}


def _parse_int(value: str, *, default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import SubmitConfig
from .submissions_service import AuthPrincipal, principal_for_token


@dataclass(frozen=True)
class UISessionPrincipal:
    name: str
    role: str

    def as_auth_principal(self) -> AuthPrincipal:
        return AuthPrincipal(name=self.name, role=self.role, token=None)


_SESSION_KEY = "ui_principal"


def login_via_token(request: Request, cfg: SubmitConfig, token: str) -> UISessionPrincipal:
    if not (cfg.tokens or cfg.token_identities):
        raise HTTPException(
            status_code=503,
            detail="UI login requires configured submit-service tokens.",
        )
    principal = principal_for_token(token, cfg)
    if principal is None:
        raise HTTPException(status_code=403, detail="Invalid token")
    data = {"name": principal.name, "role": principal.role}
    request.session[_SESSION_KEY] = data
    return UISessionPrincipal(**data)


def logout(request: Request) -> None:
    request.session.pop(_SESSION_KEY, None)


def current_ui_principal(request: Request) -> UISessionPrincipal | None:
    raw = request.session.get(_SESSION_KEY)
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    role = raw.get("role")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(role, str) or role not in {"user", "admin"}:
        return None
    return UISessionPrincipal(name=name, role=role)


def require_ui_principal(request: Request) -> UISessionPrincipal:
    principal = current_ui_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Login required")
    return principal


def require_ui_admin(request: Request) -> UISessionPrincipal:
    principal = require_ui_principal(request)
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return principal

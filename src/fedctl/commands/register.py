from __future__ import annotations

import re
from typing import Any

import tomlkit
from rich.console import Console

from fedctl.config.io import load_raw_toml, save_raw_toml
from fedctl.config.schema import EffectiveConfig
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_register(
    *,
    username: str,
    endpoint: str,
    bootstrap_token: str,
    namespace: str | None = None,
    profile: str | None = None,
    ttl: str | None = None,
    force: bool = False,
    tls_ca: str | None = None,
    tls_skip_verify: bool = False,
) -> int:
    if not _valid_username(username):
        console.print("[red]✗ Invalid username.[/red] Use letters, numbers, '-' or '_'.")
        return 1

    ns = namespace or username
    profile_name = profile or username

    cfg = EffectiveConfig(
        profile_name="register",
        endpoint=endpoint,
        namespace=None,
        tls_ca=tls_ca,
        tls_skip_verify=tls_skip_verify,
        access_mode="lan-only",
        tailscale_subnet_cidr=None,
        nomad_token=bootstrap_token,
    )

    client = NomadClient(cfg)
    policy_name = f"fedctl-user-{ns}"
    created_namespace = False
    created_policy = False
    created_token_accessor: str | None = None
    try:
        _validate_bootstrap_token(client)
        if _namespace_exists(client, ns):
            if not force:
                console.print(f"[red]✗ Namespace '{ns}' already exists.[/red]")
                return 1
        else:
            client.create_namespace(ns)
            created_namespace = True

        policy_rules = _policy_rules(ns)
        client.create_acl_policy(policy_name, policy_rules)
        created_policy = True
        
        token_payload = client.create_acl_token(
            f"fedctl-{ns}",
            [policy_name],
            ttl=ttl,
        )

        token = _extract_token(token_payload)
        created_token_accessor = _extract_accessor(token_payload)
        if not token:
            console.print("[red]✗ Token creation failed.[/red] No SecretID returned.")
            _rollback(
                client,
                ns,
                policy_name,
                created_namespace,
                created_policy,
                created_token_accessor,
            )
            return 1

        _write_profile(profile_name, endpoint, ns, force=force)
        console.print("[green]Registration complete.[/green]")
        console.print("Export this token once:")
        console.print(f"  export NOMAD_TOKEN={token}")
        console.print("This token will not be shown again.")

        # _invalidate_bootstrap_token(client)
        return 0

    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]✗ Register error:[/red] {exc}")
        _rollback(
            client,
            ns,
            policy_name,
            created_namespace,
            created_policy,
            created_token_accessor,
        )
        return 1

    except NomadHTTPError as exc:
        if exc.status_code == 403:
            console.print("[red]✗ Bootstrap token invalid or expired.[/red]")
            _rollback(
                client,
                ns,
                policy_name,
                created_namespace,
                created_policy,
                created_token_accessor,
            )
            return 1
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        _rollback(
            client,
            ns,
            policy_name,
            created_namespace,
            created_policy,
            created_token_accessor,
        )
        return 1

    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        _rollback(
            client,
            ns,
            policy_name,
            created_namespace,
            created_policy,
            created_token_accessor,
        )
        return 2

    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        _rollback(
            client,
            ns,
            policy_name,
            created_namespace,
            created_policy,
            created_token_accessor,
        )
        return 4

    finally:
        client.close()


def _valid_username(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value))


def _validate_bootstrap_token(client: NomadClient) -> None:
    client.status_leader()


def _namespace_exists(client: NomadClient, name: str) -> bool:
    try:
        client.namespace(name)
        return True
    except NomadHTTPError as exc:
        if exc.status_code == 404:
            return False
        raise


def _policy_rules(namespace: str) -> str:
    return (
        f'namespace "{namespace}" {{\n'
        '  policy = "write"\n'
        "}\n\n"
        "node {\n"
        '  policy = "read"\n'
        "}\n\n"
        "alloc {\n"
        '  policy = "read"\n'
        "}\n\n"
        "operator {\n"
        '  policy = "read"\n'
        "}\n"
    )


def _extract_token(payload: Any) -> str | None:
    if isinstance(payload, dict):
        token = payload.get("SecretID")
        if isinstance(token, str):
            return token
    return None


def _extract_accessor(payload: Any) -> str | None:
    if isinstance(payload, dict):
        accessor = payload.get("AccessorID")
        if isinstance(accessor, str):
            return accessor
    return None


def _write_profile(name: str, endpoint: str, namespace: str, *, force: bool) -> None:
    doc = load_raw_toml()
    profiles = doc.get("profiles", {})
    if name in profiles and not force:
        raise ValueError(f"Profile '{name}' already exists.")

    if "profiles" not in doc:
        doc["profiles"] = tomlkit.table()
    profiles = doc["profiles"]
    p = tomlkit.table()
    p["endpoint"] = endpoint
    p["namespace"] = namespace
    p["tls_skip_verify"] = False
    p["access_mode"] = "lan-only"
    p["tailscale"] = tomlkit.table()
    profiles[name] = p
    doc["active_profile"] = name
    save_raw_toml(doc)


def _rollback(
    client: NomadClient,
    namespace: str,
    policy_name: str,
    created_namespace: bool,
    created_policy: bool,
    token_accessor: str | None,
) -> None:
    if token_accessor:
        try:
            client.delete_acl_token(token_accessor)
        except Exception:
            pass
    if created_policy:
        try:
            client.delete_acl_policy(policy_name)
        except Exception:
            pass
    if created_namespace:
        try:
            client.delete_namespace(namespace)
        except Exception:
            pass


def _invalidate_bootstrap_token(client: NomadClient) -> None:
    try:
        info = client.acl_token_self()
    except Exception:
        console.print("[yellow]Warning:[/yellow] Failed to inspect bootstrap token.")
        return

    if isinstance(info, dict):
        accessor = info.get("AccessorID")
        if isinstance(accessor, str) and accessor:
            try:
                client.delete_acl_token(accessor)
            except Exception:
                console.print("[yellow]Warning:[/yellow] Failed to revoke bootstrap token.")

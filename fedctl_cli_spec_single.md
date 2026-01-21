# fedctl CLI Spec (current codebase)

*Updated: 2026-01-20*

This spec reflects the **implemented** CLI and behavior.

---

## Global config and auth

- User config: `~/.config/fedctl/config.toml`
- Token: `NOMAD_TOKEN` or `--token`
- Namespace: required for most Nomad operations (no implicit default)
- ACLs: token required **only if** Nomad ACLs are enabled

Env overrides:
- `FEDCTL_PROFILE`, `FEDCTL_ENDPOINT`, `FEDCTL_NAMESPACE`, `NOMAD_TOKEN`

---

## Profiles

- `fedctl profile ls`
- `fedctl profile add NAME --endpoint ... [--namespace ...] [--access-mode ...] [--tls-ca ...] [--tls-skip-verify] [--tailscale-subnet-cidr ...]`
- `fedctl profile set NAME [--endpoint ...] [--namespace ...] [--access-mode ...] [--tls-ca ...] [--tls-skip-verify] [--tailscale-subnet-cidr ...] [--clear-namespace] [--clear-tls-ca] [--clear-tailscale-subnet]`
- `fedctl profile use NAME`
- `fedctl profile rm NAME`

---

## Core commands

### `fedctl ping`
- Quick reachability check (`/v1/status/leader`).

### `fedctl doctor`
- Connectivity + TLS sanity checks.

### `fedctl discover`
- List Nomad nodes and labels.

### `fedctl local up|down|status`
- Manage local Nomad harness (HCL-based).

---

## Project inspection and config

### `fedctl inspect [PATH]`
- Validates Flower project (`pyproject.toml`)
- Prints serverapp/clientapp + federations

### `fedctl address [--exp EXP] [--format plain|toml]`
- Resolves SuperLink control address from allocation IP + control port

### `fedctl configure PATH [--exp EXP] [--backup/--no-backup]`
- Patches `pyproject.toml` with
  ```toml
  [tool.flwr.federations.remote-deployment]
  address = "<IP:PORT>"
  insecure = true
  ```

---

## Build / deploy / run

### `fedctl build PATH`
- Builds a SuperExec image (Docker)
- Uses a deterministic Dockerfile
- `--verbose` shows Docker logs (default is quiet)

### `fedctl deploy`
- Renders Nomad JSON jobs and submits them
- Requires `--image`
- `--exp` prefixes job/service names for isolation
- `--dry-run` emits JSON without submitting

### `fedctl run`
- End-to-end: inspect → build → deploy → configure → `flwr run`
- Default `--auto-supernodes` reads `local-simulation.options.num-supernodes`
- Default experiment name: `<project>-<timestamp>`

---

## Ops

### `fedctl status <exp> [--all]`
- Shows allocation status for experiment jobs

### `fedctl destroy <exp> [--all] [--purge]`
- Stops jobs for one experiment (or all experiments)
- Removes manifest for each experiment

---

## Registration

### `fedctl register USERNAME`
- Uses a short-lived bootstrap token to:
  - create namespace
  - create ACL policy
  - mint a user token
  - write local profile (no token persisted)

Required flags:
- `--endpoint`, `--bootstrap-token`

Optional flags:
- `--namespace` (default USERNAME)
- `--profile` (default USERNAME)
- `--ttl`, `--force`

---

## Exit codes (current usage)
- `0`: success
- `1`: generic/config/project error
- `2`: TLS error
- `3`: Nomad HTTP error (403 etc.)
- `4`: connection error
- `5`: project error (validation)

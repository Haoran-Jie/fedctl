# fedctl CLI Spec (current codebase)

*Updated: 2026-01-20*

This spec reflects the **implemented** CLI and behavior as of today.

---

## Quick start (end-to-end)

```bash
# 1) Build image
fedctl build .

# 2) Deploy with explicit image
fedctl deploy --image myproj-superexec:abc123 --exp exp1 --namespace alice

# 3) Patch pyproject with resolved address
fedctl configure . --exp exp1 --namespace alice

# 4) Run Flower
flwr run . remote-deployment --stream
```

Or one command:
```bash
fedctl run . --exp exp1 --namespace alice
```

---

## Global config and auth

- User config: `~/.config/fedctl/config.toml`
- Token: `NOMAD_TOKEN` or `--token`
- Namespace: required for most Nomad operations
- ACLs: token required **only if** ACLs are enabled

Env overrides:
- `FEDCTL_PROFILE`, `FEDCTL_ENDPOINT`, `FEDCTL_NAMESPACE`, `NOMAD_TOKEN`

---

## Profiles

### List profiles
```bash
fedctl profile ls
```

### Add a profile
```bash
fedctl profile add lab --endpoint https://nomad.lab:4646 --namespace alice
```

### Update a profile
```bash
fedctl profile set lab --namespace exp1
fedctl profile set lab --repo-config /path/to/.fedctl/fedctl.yaml
```

### Use a profile
```bash
fedctl profile use lab
```

---

## Project inspection and config

### `fedctl inspect [PATH]`
Validates `pyproject.toml`, prints serverapp/clientapp/federations.
```bash
fedctl inspect .
```

### `fedctl address`
Resolve SuperLink control address using allocation **IP + control port**.
```bash
fedctl address --exp exp1 --namespace alice
fedctl address --exp exp1 --format toml
```

### `fedctl configure PATH`
Patch `pyproject.toml` with federation stanza:
```toml
[tool.flwr.federations.remote-deployment]
address = "<IP:PORT>"
insecure = true
```
```bash
fedctl configure . --exp exp1 --namespace alice
```

---

## Build / deploy / run

### `fedctl build PATH`
Build a SuperExec image (Docker). Logs are quiet by default.
```bash
fedctl build . --flwr-version 1.26.0
fedctl build . --image myproj-superexec:dev --verbose
```

### `fedctl deploy`
Render + submit Nomad jobs (SuperLink, SuperNodes, SuperExec).
```bash
fedctl deploy --image myproj-superexec:dev --exp exp1 --namespace alice
```

Options:
- `--dry-run` prints rendered JSON
- `--out rendered/` writes JSON files
- `--exp` prefixes jobs/services (required for multi-user isolation)

Device-aware SuperNodes:
```bash
fedctl deploy --image myimg --exp exp1 --namespace alice \
  --supernodes rpi=2,jetson=2 --allow-oversubscribe
```

### `fedctl run`
End-to-end: inspect → build → deploy → configure → `flwr run`.
```bash
fedctl run . --exp exp1 --namespace alice
```

---

## Ops

### `fedctl status <exp>`
Shows allocation status for an experiment.
```bash
fedctl status exp1 --namespace alice
fedctl status --all --namespace alice
```

### `fedctl destroy <exp>`
Stops jobs for an experiment (optionally purge).
```bash
fedctl destroy exp1 --namespace alice
fedctl destroy --all --purge --namespace alice
```

---

## Registration

### `fedctl register USERNAME`
Bootstrap a user namespace and scoped ACL token.
```bash
fedctl register alice \
  --endpoint https://nomad.lab:4646 \
  --bootstrap-token s.bootstrap123
```

Output includes a one-time token to export:
```
export NOMAD_TOKEN=s.user_token
```

---

## Exit codes (current usage)
- `0`: success
- `1`: generic/config/project error
- `2`: TLS error
- `3`: Nomad HTTP error (403 etc.)
- `4`: connection error
- `5`: project error (validation)

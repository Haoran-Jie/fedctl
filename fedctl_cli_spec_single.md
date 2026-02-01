# fedctl CLI Spec (current codebase)

*Updated: 2026-01-22*

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

## Config, profiles, auth

- User config file: `~/.config/fedctl/config.toml`
- Repo config (optional): `.fedctl/fedctl.yaml` (or override via `--repo-config`)
- Env overrides: `FEDCTL_PROFILE`, `FEDCTL_ENDPOINT`, `FEDCTL_NAMESPACE`, `NOMAD_TOKEN`
- Most Nomad commands accept: `--profile`, `--endpoint`, `--namespace`, `--token`, `--tls-ca`, `--tls-skip-verify`
- ACLs: a token is required only if Nomad ACLs are enabled.

Access modes (profile `access_mode`):
- `lan-only` (default)
- `tailscale-mesh`
- `tailscale-subnet` (use `tailscale.subnet_cidr`)
- `ssh-tunnel`

---

## Command reference

### `fedctl config show`
Show the effective configuration.

Flags: none

Example:
```bash
fedctl config show
```

---

### `fedctl profile ls`
List profiles and highlight the active one.

Flags: none

Example:
```bash
fedctl profile ls
```

---

### `fedctl profile use NAME`
Set the active profile.

Flags: none

Example:
```bash
fedctl profile use lab
```

---

### `fedctl profile add NAME`
Create a new profile.

Flags:
- `--endpoint <url>`: Nomad API endpoint stored in the profile. Required.
- `--namespace <name>`: Default namespace for this profile.
- `--repo-config <path>`: Default repo config path stored in the profile.
- `--access-mode <lan-only|tailscale-mesh|tailscale-subnet|ssh-tunnel>`: Connectivity mode hints (affects warnings/help text). Default `lan-only`.
- `--tls-ca <path>`: CA bundle to trust for TLS connections.
- `--tls-skip-verify`: Disable TLS certificate verification.
- `--tailscale-subnet-cidr <cidr>`: Subnet route to use when `access_mode=tailscale-subnet`.

Examples:
```bash
fedctl profile add lab --endpoint https://nomad.lab:4646 --namespace alice
fedctl profile add lab --endpoint https://nomad.lab:4646 --access-mode tailscale-subnet \
  --tailscale-subnet-cidr 100.64.0.0/10
```

---

### `fedctl profile set NAME`
Update an existing profile.

Flags:
- `--endpoint <url>`: Update the profile endpoint.
- `--namespace <name>`: Update the default namespace.
- `--repo-config <path>`: Update the stored repo config path.
- `--access-mode <lan-only|tailscale-mesh|tailscale-subnet|ssh-tunnel>`: Update connectivity mode hints.
- `--tls-ca <path>`: Update the trusted CA bundle path.
- `--tls-skip-verify`: Enable/disable TLS verification for this profile.
- `--tailscale-subnet-cidr <cidr>`: Update tailscale subnet route.
- `--clear-namespace`: Remove the namespace from the profile.
- `--clear-repo-config`: Remove the repo config path.
- `--clear-tls-ca`: Remove the custom CA path.
- `--clear-tailscale-subnet`: Remove the tailscale subnet route.

Examples:
```bash
fedctl profile set lab --namespace alice
fedctl profile set lab --repo-config /path/to/.fedctl/fedctl.yaml
fedctl profile set lab --clear-repo-config --clear-namespace
```

---

### `fedctl profile rm NAME`
Remove a profile (cannot remove the active profile).

Flags: none

Example:
```bash
fedctl profile rm oldlab
```

---

### `fedctl doctor`
Check config resolution and Nomad connectivity.

Flags:
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--namespace <name>`: Override namespace for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Example:
```bash
fedctl doctor --profile lab
```

---

### `fedctl ping`
Quick connectivity check to Nomad (`/v1/status/leader`).

Flags:
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--namespace <name>`: Override namespace for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Example:
```bash
fedctl ping --endpoint https://nomad.lab:4646
```

---

### `fedctl discover`
List Nomad nodes and extracted device metadata.

Flags:
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--namespace <name>`: Override namespace for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).
- `--wide`: Add extra columns (arch, OS, node ID).
- `--json`: Print raw Nomad node JSON instead of a table.
- `--device <device>`: Filter by node device label (from metadata).
- `--status <status>`: Filter by node status (e.g., `ready`).
- `--class <node_class>`: Filter by Nomad node class.

Examples:
```bash
fedctl discover
fedctl discover --wide --status ready
fedctl discover --device rpi --class edge
fedctl discover --json
```

---

### `fedctl inspect [PATH]`
Inspect a Flower project for fedctl metadata.

Flags: none

Example:
```bash
fedctl inspect .
```

---

### `fedctl build [PATH]`
Build a SuperExec image for a Flower project.

Flags:
- `--flwr-version <ver>`: Flower version embedded into the generated Dockerfile. Default `1.25.0`.
- `--image <name>`: Output image tag; defaults to a repo-derived tag.
- `--no-cache`: Disable Docker layer cache.
- `--platform <platform>`: Target platform for Docker build (e.g., `linux/amd64`).
- `--context <path>`: Override Docker build context (defaults to project root).
- `--push`: Push the image after successful build.
- `--verbose`: Show full Docker output (disable quiet mode).

Examples:
```bash
fedctl build .
fedctl build . --flwr-version 1.26.0 --image myproj-superexec:dev --verbose
fedctl build . --platform linux/amd64 --no-cache --push
```

---

### `fedctl deploy`
Render and submit Nomad jobs (SuperLink, SuperNodes, SuperExec).

Flags:
- `--dry-run`: Render jobs only; do not submit to Nomad.
- `--out <dir>`: Write rendered JSON to a directory (only valid with `--dry-run`). Defaults to `rendered/` when omitted.
- `--format <json>`: Output format for rendered jobs. Only `json` is supported.
- `--num-supernodes <n>`: Number of SuperNode instances to deploy. Default `2` when no typed `deploy.supernodes` is set in repo config.
- `--supernodes <spec>`: Typed counts, e.g., `rpi=2` or `rpi=2,jetson=1`. Repeatable.
- `--net <spec>`: Network profile assignments, e.g., `rpi[1]=med,jetson[*]=high`. Repeatable.
- `--allow-oversubscribe / --no-allow-oversubscribe`: If set, place multiple supernodes on one device type without inventory checks.
- `--repo-config <path>`: Load `.fedctl/fedctl.yaml` from a repo or override path.
- `--image <name>`: SuperExec Docker image to deploy. Required.
- `--exp <name>`: Experiment name prefix for jobs/services. Default `<project>-<timestamp>` when a project is detected, otherwise `experiment`.
- `--timeout <seconds>`: Wait timeout for SuperLink readiness. Default `120`.
- `--no-wait`: Skip readiness wait and manifest creation.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--namespace <name>`: Override namespace for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Notes:
- `--num-supernodes` and `--supernodes` are mutually exclusive.
- Non-oversubscribed placement with `--supernodes` requires live inventory and cannot be used with `--dry-run`.
- `--net` requires `deploy.network.image` in `.fedctl/fedctl.yaml` and Nomad tasks must allow `NET_ADMIN`.

Examples:
```bash
fedctl deploy --image myproj-superexec:dev --exp exp1 --namespace alice
fedctl deploy --image myimg --exp exp1 --namespace alice \
  --supernodes rpi=2,jetson=2 --allow-oversubscribe
fedctl deploy --image myimg --dry-run --out rendered/
```

---

### `fedctl address`
Resolve the SuperLink control address.

Flags:
- `--namespace <name>`: Namespace to search for SuperLink allocations.
- `--exp <name>`: Experiment name; used to select the SuperLink job.
- `--format <plain|toml>`: Output format. `toml` prints a federation stanza. Default `plain`.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Examples:
```bash
fedctl address --exp exp1 --namespace alice
fedctl address --exp exp1 --format toml
```

---

### `fedctl configure [PATH]`
Patch `pyproject.toml` with the resolved federation address.

Flags:
- `--namespace <name>`: Namespace to use when resolving SuperLink.
- `--exp <name>`: Experiment name to resolve the SuperLink allocation.
- `--backup / --no-backup`: Keep or skip a backup of `pyproject.toml`. Default `--backup`.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Example:
```bash
fedctl configure . --exp exp1 --namespace alice
```

---

### `fedctl run [PATH]`
End-to-end: inspect → build → deploy → configure → `flwr run`.

Flags:
- `--flwr-version <ver>`: Flower version embedded into the generated Dockerfile. Default `1.25.0`.
- `--image <name>`: Output image tag; defaults to a repo-derived tag.
- `--no-cache`: Disable Docker layer cache.
- `--platform <platform>`: Target platform for Docker build (e.g., `linux/amd64`).
- `--context <path>`: Override Docker build context (defaults to project root).
- `--push`: Push the image after successful build.
- `--num-supernodes <n>`: Number of SuperNode instances to deploy. Default `2`.
- `--auto-supernodes / --no-auto-supernodes`: If enabled, read `local_sim_num_supernodes` from the project and use it. Default enabled.
- `--supernodes <spec>`: Typed counts, e.g., `rpi=2` or `rpi=2,jetson=1`. Repeatable.
- `--net <spec>`: Network profile assignments, e.g., `rpi[1]=med,jetson[*]=high`. Repeatable.
- `--allow-oversubscribe / --no-allow-oversubscribe`: Allow placement without matching node inventory.
- `--repo-config <path>`: Load `.fedctl/fedctl.yaml` from a repo or override path.
- `--exp <name>`: Experiment name prefix. Default `<project>-<timestamp>`.
- `--timeout <seconds>`: Wait timeout for SuperLink readiness. Default `120`.
- `--no-wait`: Skip readiness wait and manifest creation.
- `--namespace <name>`: Override namespace for this run.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this run.
- `--token <token>`: Override NOMAD token for this run.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).
- `--federation <name>`: Federation name passed to `flwr run`. Default `remote-deployment`.
- `--stream / --no-stream`: Toggle streaming logs in `flwr run`. Default enabled.
- `--verbose`: Show full Docker output during build.

Examples:
```bash
fedctl run . --exp exp1 --namespace alice
fedctl run . --supernodes rpi=4 --allow-oversubscribe --no-wait
fedctl run . --federation remote-deployment --no-stream
```

Notes:
- `--net` requires `deploy.network.image` in `.fedctl/fedctl.yaml` and Nomad tasks must allow `NET_ADMIN`.

---

### `fedctl status [EXP]`
Show allocation status for an experiment.

Flags:
- `--all`: Ignore `EXP` and show all experiments.
- `--namespace <name>`: Override namespace for this call.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Examples:
```bash
fedctl status exp1 --namespace alice
fedctl status --all --namespace alice
```

Notes:
- When a deployment manifest exists, `fedctl status` also prints a per-SuperNode table with node ID and net profile.

---

### `fedctl destroy [EXP]`
Stop jobs for an experiment (optionally purge).

Flags:
- `--purge`: Purge jobs and allocations instead of a soft stop.
- `--all`: Ignore `EXP` and destroy all experiments.
- `--namespace <name>`: Override namespace for this call.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this call.
- `--token <token>`: Override NOMAD token for this call.
- `--tls-ca <path>`: Override TLS CA bundle.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Examples:
```bash
fedctl destroy exp1 --namespace alice
fedctl destroy --all --purge --namespace alice
```

---

### `fedctl register USERNAME`
Register a user namespace and scoped ACL token using a bootstrap token.

Flags:
- `--endpoint <url>`: Nomad API endpoint for bootstrap operations. Required.
- `--bootstrap-token <token>`: Bootstrap token with ACL management rights. Required.
- `--namespace <name>`: Namespace to create/use; defaults to USERNAME.
- `--profile <name>`: Profile name to create/use; defaults to USERNAME.
- `--ttl <duration>`: Token TTL (e.g., `24h`), passed to Nomad.
- `--force`: Overwrite existing namespace/profile if present.
- `--tls-ca <path>`: CA bundle to trust for TLS connections.
- `--tls-skip-verify`: Skip TLS verification (dev only).

Example:
```bash
fedctl register alice \
  --endpoint https://nomad.lab:4646 \
  --bootstrap-token s.bootstrap123
```

---

### `fedctl local up`
Start a local Nomad harness from HCL configs.

Flags:
- `--server <path>`: Nomad server agent HCL config. Required.
- `--client <path>`: Nomad client agent HCL config. Repeatable; at least one required (`-c` also works).
- `--wipe`: Clear local data/logs before starting.
- `--wait-seconds <n>`: Time to wait for readiness before failing. Default `30`.
- `--expected-nodes <n>`: Expected node count before marking ready.
- `--endpoint <url>`: Reserved; currently unused.

Example:
```bash
fedctl local up --server nomad/server.hcl --client nomad/client.hcl --client nomad/client2.hcl
```

---

### `fedctl local down`
Stop the local Nomad harness.

Flags:
- `--wipe`: Remove cached state and logs after stopping.
- `--force`: Send SIGKILL if agents do not exit cleanly.

Example:
```bash
fedctl local down --wipe
```

---

### `fedctl local status`
Show local harness status.

Flags: none

Example:
```bash
fedctl local status
```

---

## Exit codes (current usage)
- `0`: success
- `1`: generic/config/project error
- `2`: TLS error
- `3`: Nomad HTTP error (403, etc.)
- `4`: connection error
- `5`: project error (validation)

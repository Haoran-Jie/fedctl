# fedctl CLI Spec (current codebase)

*Updated: 2026-02-21*

This spec reflects the **implemented** CLI and behavior as of today.

---

## Help Visibility

- `fedctl --help` shows all commands.
- `submit` is listed first in the command table.

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
- Most Nomad commands accept: `--profile`, `--endpoint`, `--namespace`, `--token`
- ACLs: a token is required only if Nomad ACLs are enabled.

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

Examples:
```bash
fedctl profile add lab --endpoint https://nomad.lab:4646 --namespace alice
```

---

### `fedctl profile set NAME`
Update an existing profile.

Flags:
- `--endpoint <url>`: Update the profile endpoint.
- `--namespace <name>`: Update the default namespace.
- `--repo-config <path>`: Update the stored repo config path.
- `--clear-namespace`: Remove the namespace from the profile.
- `--clear-repo-config`: Remove the repo config path.

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

## Submit service commands

### `fedctl submit run [PATH]`
Submit a project for queued execution via the submit service.

Use this for the normal remote cluster workflow from the laptop.
`fedctl run` is the direct Nomad path and is not the same thing.

Flags:
- `--flwr-version <ver>`: Flower version for the SuperExec image. Default `1.25.0`.
- `--image <name>`: SuperExec image tag override.
- `--no-cache`: Disable Docker build cache.
- `--platform <platform>`: Docker build platform.
- `--context <path>`: Override Docker build context.
- `--push`: Push SuperExec image after build.
- `--num-supernodes <n>`: Number of SuperNode instances. Default `2`.
- `--auto-supernodes / --no-auto-supernodes`: Use project metadata to set supernode count. Default enabled.
- `--supernodes <spec>`: Typed counts, e.g., `rpi=2`. Repeatable.
- `--net <spec>`: Network profile assignments, e.g., `rpi[1]=med,jetson[*]=high`. Repeatable.
  - Tuple syntax is supported: `rpi[1]=(low,high)` sets ingress=low, egress=high.
- `--allow-oversubscribe / --no-allow-oversubscribe`: Allow placement without matching node inventory.
- `--repo-config <path>`: Override repo config path.
- `--exp <name>`: Experiment name prefix.
- `--timeout <seconds>`: Wait timeout. Default `120`.
- `--federation <name>`: Federation name for `flwr run`. Default `remote-deployment`.
- `--stream / --no-stream`: Stream `flwr run` logs. Default enabled.
- `--verbose`: Show full build output.
- `--destroy / --no-destroy`: Destroy Nomad jobs after run. Default `--destroy`.
- `--submit-image <image>`: Override submit runner image.
- `--artifact-store <url>`: Override artifact store (e.g., `s3+presign://...`).
- `--priority <n>`: Queue priority (submit service).

Example:
```bash
fedctl submit run . --exp exp1 --no-destroy
```

---

### `fedctl submit status <ID>`
Show status for a submitted job.

Example:
```bash
fedctl submit status sub-20260201-1234
```

---

### `fedctl submit cancel <ID>`
Cancel a submitted job.

Example:
```bash
fedctl submit cancel sub-20260201-1234
```

---

### `fedctl submit logs <ID>`
Fetch logs for a submitted job.

Flags:
- `--job <name>`: One of `submit`, `superlink`, `supernodes`, `superexec_serverapp`, `superexec_clientapps`.
- `--task <name>`: Task name inside job.
- `--index <n>`: Index for grouped jobs. Use this for `superexec_clientapps`, and optionally for `supernodes`.
- `--stderr / --stdout`: Select stream.
- `--follow`: Stream logs.

Examples:
```bash
fedctl submit logs <id>
fedctl submit logs <id> --job supernodes --task supernode-1
fedctl submit logs <id> --job supernodes --index 2
fedctl submit logs <id> --job superexec_clientapps --index 2
```

---

### `fedctl submit ls`
List recent submissions.

Flags:
- `--limit <n>`: Max rows. Default `20`.
- `--active`: Show only queued/running/blocked submissions.
- `--completed`: Show only completed submissions.
- `--failed`: Show only failed submissions.
- `--cancelled`: Show only cancelled submissions.
- `--all`: Show all submissions.

Example:
```bash
fedctl submit ls
fedctl submit ls --completed
```

---

### `fedctl submit inventory`
Show Nomad node inventory via the submit service.

Flags:
- `--include-allocs`: Include allocation details (default).
- `--detail`: Show per-alloc resource details.
- `--json`: Raw JSON output.
- `--status <status>`: Filter by node status.
- `--class <node_class>`: Filter by node class.
- `--device-type <type>`: Filter by device type.

Example:
```bash
fedctl submit inventory --detail
```

---

### `fedctl submit results <ID>`
Show or download result artifacts for a submission.

Flags:
- `--download`: Download artifacts instead of printing.
- `--out <path>`: Output file/dir for downloads.
- `--show-url`: Print full URLs (default is a short display).

Examples:
```bash
fedctl submit results <id>
fedctl submit results <id> --show-url
fedctl submit results <id> --download --out ./results
```

---

### `fedctl submit purge`
Clear submit-service and local submission history.

Example:
```bash
fedctl submit purge
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
  - Tuple syntax is supported: `rpi[1]=(low,high)` sets ingress=low, egress=high.
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

Example:
```bash
fedctl configure . --exp exp1 --namespace alice
```

---

### `fedctl run [PATH]`
End-to-end: inspect → build → deploy → configure → `flwr run`.

This is the direct Nomad workflow. It does not go through the submit service.
For the normal queued remote workflow from the laptop, use `fedctl submit run`
instead.

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
  - Tuple syntax is supported: `rpi[1]=(low,high)` sets ingress=low, egress=high.
- `--allow-oversubscribe / --no-allow-oversubscribe`: Allow placement without matching node inventory.
- `--repo-config <path>`: Load `.fedctl/fedctl.yaml` from a repo or override path.
- `--exp <name>`: Experiment name prefix. Default `<project>-<timestamp>`.
- `--timeout <seconds>`: Wait timeout for SuperLink readiness. Default `120`.
- `--no-wait`: Skip readiness wait and manifest creation.
- `--namespace <name>`: Override namespace for this run.
- `--profile <name>`: Use a specific profile instead of the active one.
- `--endpoint <url>`: Override Nomad endpoint for this run.
- `--token <token>`: Override NOMAD token for this run.
- `--federation <name>`: Federation name passed to `flwr run`. Default `remote-deployment`.
- `--stream / --no-stream`: Toggle streaming logs in `flwr run`. Default enabled.
- `--verbose`: Show full Docker output during build.
- `--destroy / --no-destroy`: Destroy Nomad jobs after the run. Default `--destroy`.

Examples:
```bash
fedctl run . --exp exp1 --namespace alice
fedctl run . --supernodes rpi=4 --allow-oversubscribe --no-wait
fedctl run . --federation remote-deployment --no-stream
```

Notes:
- `--net` requires `deploy.network.image` in `.fedctl/fedctl.yaml` and Nomad tasks must allow `NET_ADMIN`.

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

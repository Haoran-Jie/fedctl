# fedctl CLI Spec (MVP + near-term extensions)

This document defines the **command-line interface**, **flags**, and **configuration layout** for `fedctl`, the tool that:
1) connects to a remote Nomad cluster (via VPN or SSH tunnel),
2) deploys Flower Fabric components (e.g., SuperLink/SuperNodes),
3) discovers the reachable SuperLink address,
4) patches the local project's `pyproject.toml` with a `remote-deployment` federation stanza,
5) prints the command the user should run: `flwr run . remote-deployment --stream`.

---

## 0) Mental model

`fedctl` manages **deployments** on a remote lab cluster and writes **connection metadata** into the user's local Flower app so the user can run Flower CLI against the deployed Fabric.

Key objects:
- **Profile**: how `fedctl` connects/authenticates to Nomad (endpoint, TLS, namespace).
- **Deployment (exp)**: a named instance of a running Fabric (jobs + allocations) created by `fedctl`.

---

## 1) Global conventions

### 1.1 Exit codes (recommended)
- `0`: success
- `1`: generic error
- `2`: config error (missing/invalid endpoint, token, profile)
- `3`: connectivity error (DNS, timeout, TLS)
- `4`: Nomad API error (permission, invalid job spec)
- `5`: project error (missing pyproject, invalid toml)

### 1.2 Output formats
Default: human-readable.
Optional:
- `--json`: machine-readable structured output (where applicable)

### 1.3 Environment variables
- `NOMAD_TOKEN`: Nomad ACL token (preferred)
- `FEDCTL_PROFILE`: overrides active profile name
- `FEDCTL_ENDPOINT`: overrides endpoint (debug)
- `FEDCTL_NAMESPACE`: overrides namespace (debug)

---

## 2) Global flags (apply to all commands)

| Flag | Type | Default | Purpose |
|---|---|---:|---|
| `--profile` | string | active profile | select profile |
| `--endpoint` | URL | from profile | override Nomad endpoint |
| `--namespace` | string | from profile | override Nomad namespace |
| `--token` | string | from env (`NOMAD_TOKEN`) | override token |
| `--tls-ca` | path | from profile | CA bundle for TLS |
| `--tls-skip-verify` | bool | false | skip TLS verification (dev only) |
| `--timeout` | seconds | 30 | HTTP timeout |
| `--json` | bool | false | JSON output |
| `-v/--verbose` | count | 0 | increase verbosity (repeatable) |

---

## 3) Configuration file layout

### 3.1 User-level config file (required)
Locations:
- macOS/Linux: `~/.config/fedctl/config.toml`
- Windows: `%APPDATA%\\fedctl\\config.toml`

Example `config.toml`:
```toml
active_profile = "lab-vpn"

[state]
dir = "~/.local/share/fedctl"  # deployments/manifests (default ok)

[profiles.lab-vpn]
endpoint = "https://nomad.lab.domain:4646"
namespace = "samuel"
tls_ca = "/Users/samuel/.config/fedctl/lab-ca.pem"
tls_skip_verify = false

# Optional quality-of-life for tunnel mode
[profiles.lab-tunnel]
endpoint = "https://nomad.lab.domain:4646"
namespace = "samuel"
tls_skip_verify = false
hint = "ssh -L 4646:nomad-server:4646 -L 27738:nomad-server:27738 user@jumphost && sudo sh -c 'echo 127.0.0.1 nomad.lab.domain >> /etc/hosts'"
```

Token handling (MVP):
- read `NOMAD_TOKEN`
- if `--token` provided, use it for this invocation only
- DO NOT store tokens in plaintext config for MVP

### 3.2 Repo-level config file (optional)
In the user’s Flower app repo:
- `.fedctl/fedctl.yaml`

Purpose:
- provide defaults for deploy/configure without requiring many CLI flags

Example `.fedctl/fedctl.yaml`:
```yaml
flwr_version: "1.23.0"
federation_name: "remote-deployment"

deploy:
  server_port: 27738
  clients: 4
  artifact_dir: "/shared/fedctl"
  constraints:
    superlink: "node.class == management"
    clients: "node.class != management"
  resources:
    superlink: { cpu: 500, mem: 512 }
    supernode: { cpu: 500, mem: 512 }

configure:
  insecure: true
  backup: true
```

---

## 4) Commands

### 4.1 `fedctl config`
Inspect and edit global config quickly.

#### `fedctl config show`
Print active profile and settings (excluding secrets).
```bash
fedctl config show
```

#### `fedctl profile ls`
```bash
fedctl profile ls
```

#### `fedctl profile add`
```bash
fedctl profile add NAME --endpoint URL [--namespace NS] [--tls-ca PATH] [--tls-skip-verify]
```

#### `fedctl profile use`
```bash
fedctl profile use NAME
```

#### `fedctl profile rm`
```bash
fedctl profile rm NAME
```

---

### 4.2 `fedctl ping`
Connectivity check: endpoint reachable, token valid, namespace accessible.
```bash
fedctl ping
```

Outputs:
- endpoint
- namespace
- Nomad leader (or error)
- Nomad version (optional)

---

### 4.3 `fedctl doctor`
More verbose diagnostics, especially for tunnel/TLS issues.
```bash
fedctl doctor
```

Checks:
- DNS resolution
- TCP connect
- TLS validation / hostname mismatch guidance
- token presence + permission sanity (e.g., `GET /v1/nodes`)

---

### 4.4 `fedctl discover`
List nodes and capabilities.

```bash
fedctl discover [--filter KEY=VALUE]... [--wide] [--json]
```

Examples:
```bash
fedctl discover
fedctl discover --filter node.class=jetson --wide
fedctl discover --json
```

Recommended output columns:
- NodeName
- Status
- Class (e.g. management/pi/jetson)
- CPU/Mem
- Meta: arch, gpu=true/false

---

### 4.5 `fedctl init`
Create `.fedctl/` in the repo (optional helper).
```bash
fedctl init [PATH] [--name NAME]
```

Creates:
- `.fedctl/fedctl.yaml` (with inferred defaults)
- `.fedctl/README.md` (basic notes)

---

### 4.6 `fedctl build` (optional for MVP; but in your "ideal usecase")
Build and optionally push user app image.

```bash
fedctl build [PATH] \
  [--flwr-version 1.23.0] \
  [--tag TAG] \
  [--registry REGISTRY] \
  [--push/--no-push] \
  [--dockerfile-mode auto|generated|existing] \
  [--image IMAGE_REF] \
  [--platform linux/arm64|linux/amd64|linux/arm64,linux/amd64]
```

Semantics:
- If `--image` is provided, `fedctl` skips build and uses it.
- `dockerfile-mode`:
  - `auto`: use existing Dockerfile if present, else generate canonical Dockerfile
  - `generated`: always generate and use fedctl canonical Dockerfile
  - `existing`: require Dockerfile at repo root

Outputs:
- resolved `image_ref` (fully qualified tag)

---

### 4.7 `fedctl deploy`
Deploy Flower Fabric to remote cluster via Nomad.

```bash
fedctl deploy [PATH] \
  --name EXP_NAME \
  --image IMAGE_REF \
  [--clients N] \
  [--server-port PORT] \
  [--federation-name NAME] \
  [--constraint-superlink EXPR] \
  [--constraint-clients EXPR] \
  [--resources-superlink cpu=...,mem=...] \
  [--resources-supernode cpu=...,mem=...] \
  [--artifact-dir PATH] \
  [--network-mode host|bridge] \
  [--dry-run]
```

Defaults:
- `--federation-name remote-deployment`
- `--server-port 27738`
- `--constraint-superlink "node.class == management"` (recommended)
- `--network-mode host` (recommended for reachability)

Examples:
```bash
fedctl deploy . --name demo --image ghcr.io/org/app:demo --clients 4
fedctl deploy . --name demo --image ghcr.io/org/app:demo --clients 8 --dry-run
```

Outputs:
- deployment id/name
- created Nomad job names (e.g. `fedctl-demo-superlink`, `fedctl-demo-supernode`)
- resolved federation address (see `fedctl address`)

---

### 4.8 `fedctl address`
Resolve and print the reachable SuperLink address for a deployment.

```bash
fedctl address EXP_NAME [--format plain|toml] [--print-flwr-cmd]
```

Example:
```bash
fedctl address demo --print-flwr-cmd
```

Outputs:
- `nomad.lab.domain:27738`
- optional:
  - `flwr run . remote-deployment --stream`

---

### 4.9 `fedctl configure`
Patch `pyproject.toml` to add/update the federation stanza.

```bash
fedctl configure [PATH] \
  --exp EXP_NAME \
  [--federation-name remote-deployment] \
  [--address HOST:PORT] \
  [--insecure true|false] \
  [--backup/--no-backup] \
  [--write-only]
```

Semantics:
- If `--address` is provided, use it.
- Else resolve from `--exp` using Nomad allocation info.
- Adds/updates:
```toml
[tool.flwr.federations.remote-deployment]
address = "HOST:PORT"
insecure = true
```

---

### 4.10 `fedctl status`
Show job and allocation health for the deployment.

```bash
fedctl status EXP_NAME [--json]
```

Suggested info:
- superlink alloc: running/failed + restart count
- number of supernodes running
- last transition timestamps

---

### 4.11 `fedctl destroy`
Stop and remove jobs created by the deployment.

```bash
fedctl destroy EXP_NAME [--purge]
```

Semantics:
- Deregister jobs
- `--purge` removes job history in Nomad (if permissions allow)

---

### 4.12 `fedctl run` (convenience golden-path)
One command that does build→deploy→configure and prints the Flower command.

```bash
fedctl run [PATH] \
  --name EXP_NAME \
  [--clients N] \
  [--flwr-version 1.23.0] \
  [--registry REGISTRY] \
  [--tag TAG] \
  [--push/--no-push] \
  [--federation-name remote-deployment] \
  [--insecure true|false]
```

Example:
```bash
fedctl run . --name demo --clients 4 --push
# prints:
# flwr run . remote-deployment --stream
```

---

## 5) Naming conventions

### 5.1 Nomad job names
`fedctl-{namespace}-{exp}-{component}` (keep short)
Examples:
- `fedctl-samuel-demo-superlink`
- `fedctl-samuel-demo-supernode`

### 5.2 Deployment manifest
Stored under `${state.dir}/{namespace}/deployments/{exp}.json`
Tracks:
- endpoint used
- namespace
- job names
- alloc ids (superlink alloc id is key)
- resolved address/ports
- timestamps

---

## 6) Notes on VPN vs SSH tunnel

`fedctl` does not “do VPN”; it just requires the endpoint to be reachable.

For SSH tunnel mode:
- endpoint should be **the same hostname** as the TLS cert (e.g. `https://nomad.lab.domain:4646`)
- user should map `nomad.lab.domain -> 127.0.0.1` while tunneling
- tunnel needs at least:
  - `4646` (Nomad API)
  - `27738` (SuperLink control port) if user runs `flwr` from their laptop

`fedctl doctor` should detect TLS mismatch and print the recommended fix.

---
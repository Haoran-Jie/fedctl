# `fedctl` Implementation Plan (Ordered Milestones)

This plan is designed to get you to a **working MVP quickly**, while keeping the architecture clean enough to extend (network shaping, fault injection, richer scheduling, logs, etc.).

Assumptions:
- `fedctl` is a **local CLI** installed on a user machine.
- `fedctl` controls the remote lab cluster **only via Nomad HTTP API**.
- SuperLink is pinned to a **management node** with a stable hostname and (ideally) a fixed host port (so users can reach it from VPN/SSH tunnel).
- Users run: `flwr run . remote-deployment --stream` locally after `fedctl configure`.

---

## Milestone 0 — Repo + packaging skeleton (0.5 day)

**Goal:** You can install and run `fedctl` locally, and CI/tests run.

Deliverables:
- Python package layout under `src/fedctl`
- CLI entrypoint (`fedctl --help`) using Typer
- `pyproject.toml` with dependencies + `console_scripts`
- pytest configured (even if only placeholder test)

Acceptance criteria:
- `pip install -e .`
- `fedctl --help` works
- `pytest` passes

Files:
- `src/fedctl/cli.py`
- `src/fedctl/__main__.py`
- `pyproject.toml`
- `tests/test_smoke.py`

---

## Milestone 1 — Config + profiles + auth plumbing (0.5–1 day)

**Goal:** `fedctl` can load profiles and produce an “effective config” (endpoint, namespace, TLS).

Deliverables:
- user config file (`~/.config/fedctl/config.toml`)
- commands:
  - `fedctl config show`
  - `fedctl profile add|use|ls|rm`
- precedence logic:
  - profile defaults → env overrides → CLI overrides

Acceptance criteria:
- can create a profile and switch active profile
- `fedctl config show` prints effective endpoint/namespace

Files:
- `fedctl/config/paths.py`, `schema.py`, `io.py`, `merge.py`
- CLI wiring in `cli.py`

---

## Milestone 2 — Nomad client wrapper + `ping`/`doctor` (1 day)

**Goal:** `fedctl` can connect to Nomad reliably with helpful errors (TLS mismatch, missing token, etc.).

Deliverables:
- Nomad HTTP client wrapper (httpx)
- commands:
  - `fedctl ping` → `GET /v1/status/leader`
  - `fedctl doctor` → `GET /v1/agent/self` + extra diagnostics
- Error mapping:
  - 403 → “token/ACL invalid”
  - TLS verify errors → show guidance (VPN vs tunnel with /etc/hosts mapping)

Acceptance criteria:
- On a reachable endpoint: `fedctl ping` prints leader
- On TLS mismatch: `doctor` explains how to fix it

Files:
- `fedctl/nomad/client.py`, `endpoints.py`, `errors.py`
- CLI commands in `cli.py`

---

## Milestone 3 — Node discovery (`discover`) (0.5 day)

**Goal:** users can see available nodes and their scheduling attributes (pi/jetson/management).

Deliverables:
- `fedctl discover` using `GET /v1/nodes`
- optional `--wide` with extra attributes
- optional `--json` output

Acceptance criteria:
- `fedctl discover` prints a reasonable table of nodes
- filters work if you implement them (optional MVP)

Files:
- `fedctl/nomad/models.py` (optional typed parsing)
- `fedctl/util/console.py` for table output

---

## Milestone 4 — Project validation + pyproject parsing (0.5–1 day)

**Goal:** `fedctl` can confirm “this directory is a Flower app repo” and read key metadata.

Deliverables:
- `fedctl init` (optional) creates `.fedctl/fedctl.yaml`
- `project.flwr_inspect` reads:
  - `[tool.flwr.app]`
  - `[tool.flwr.app.components]`
  - existing `[tool.flwr.federations]` sections

Acceptance criteria:
- run `fedctl init .` and it creates `.fedctl/`
- `fedctl` errors clearly if `pyproject.toml` missing or malformed

Files:
- `fedctl/project/flwr_inspect.py`

---

## Milestone 5 — Render Nomad job specs (dry-run deploy) (1–1.5 days)

**Goal:** `fedctl deploy --dry-run` produces correct Nomad job JSON for SuperLink + SuperNodes.

Deliverables:
- Jinja templates:
  - `templates/nomad/superlink.json.j2`
  - `templates/nomad/supernode.json.j2`
- DeploySpec structure (`deploy/spec.py`)
- `deploy/render.py` to render templates into dicts
- CLI:
  - `fedctl deploy ... --dry-run` prints or writes rendered specs

Acceptance criteria:
- rendered jobs have required Nomad fields
- SuperLink job includes:
  - constraint pin to management node
  - fixed exposed port (recommended)
- SuperNode job includes:
  - count = clients
  - args pointing at SuperLink address (or placeholder for now)

Files:
- `fedctl/deploy/spec.py`, `render.py`, `naming.py`
- templates under `templates/nomad/`

---

## Milestone 6 — Submit jobs + wait for readiness (real deploy) (1–2 days)

**Goal:** `fedctl deploy` can create jobs on Nomad and wait until SuperLink is running.

Deliverables:
- `deploy/submit.py` calls `POST /v1/jobs`
- `deploy/resolve.py` polling loop:
  - `GET /v1/job/<job>/allocations`
  - `GET /v1/allocation/<alloc_id>`
- Deployment manifest persistence (`state/manifest.py`, `state/store.py`)

Acceptance criteria:
- `fedctl deploy` returns success only when SuperLink task is running
- manifest written under state dir (by namespace/exp)
- clean failure messages if alloc fails

Files:
- `fedctl/deploy/submit.py`, `resolve.py`
- `fedctl/state/manifest.py`, `store.py`

---

## Milestone 7 — Address resolution + `fedctl address` (0.5 day)

**Goal:** compute the federation address reliably and print it (and optionally the Flower command).

Deliverables:
- `fedctl address <exp>`
- returns `nomad.lab.domain:27738` (preferred stable form)
- `--format toml` prints the exact stanza content

Acceptance criteria:
- address is correct even after restarting `fedctl` (from manifest)
- if manifest missing, attempt recompute from Nomad job state

Files:
- `fedctl/deploy/resolve.py` (re-used)
- `fedctl/state/store.py`

---

## Milestone 8 — Patch `pyproject.toml` (`configure`) (0.5–1 day)

**Goal:** update the user project with the remote deployment federation stanza.

Deliverables:
- `fedctl configure . --exp <exp>`
- Uses `tomlkit` to insert/update:
  ```toml
  [tool.flwr.federations.remote-deployment]
  address = "HOST:PORT"
  insecure = true
  ```
- optional `--backup` (default true)

Acceptance criteria:
- idempotent patch
- preserves other pyproject formatting
- prints the follow-up command:
  - `flwr run . remote-deployment --stream`

Files:
- `fedctl/project/pyproject_patch.py`

---

## Milestone 9 — End-to-end `fedctl run` (0.5 day)

**Goal:** one command does deploy + configure (build optional later).

Deliverables:
- `fedctl run . --name demo --clients 4`
  - `deploy`
  - `configure`
  - prints `flwr run ...`

Acceptance criteria:
- single command gets user from repo to runnable `flwr run`

---

## Milestone 10 — Destroy + status (0.5–1 day)

**Goal:** basic ops commands for shared lab usability.

Deliverables:
- `fedctl status <exp>`
  - summarises alloc states for superlink + supernode jobs
- `fedctl destroy <exp>`
  - deregisters jobs in order
  - `--purge` optional
  - removes manifest

Acceptance criteria:
- destroy always cleans up jobs created by the exp
- status is useful and fast

Files:
- `fedctl/deploy/status.py`, `destroy.py`

---

# Optional milestones (post-MVP)

## M11 — Build & push image (1 day)
- `fedctl build` generates Dockerfile + runs docker build/push
- integrate into `fedctl run`

## M12 — Logs (1 day)
- implement Nomad log endpoint usage or artifact-based logs

## M13 — Service discovery / Consul (2+ days)
- register SuperLink, use stable service name instead of IP/port discovery

## M14 — Network shaping / faults (2–5 days)
- add netem/toxiproxy jobs and “profiles”

---

## Suggested MVP stopping point

A defensible dissertation MVP is completing **M0–M10**:
- reproducible deploy/configure
- clear connectivity story (VPN/tunnel)
- stable address strategy
- cleanup + status for shared environment
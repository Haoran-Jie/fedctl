# `fedctl` Repo Skeleton (Python CLI) — with detailed explanations

This is a **practical, MVP-first** repository layout for `fedctl` as a Python CLI that:
- connects to a remote Nomad cluster (VPN / SSH tunnel),
- deploys Flower Fabric jobs via Nomad API,
- resolves the SuperLink address,
- patches a local Flower app’s `pyproject.toml`.

It’s designed so you can build in layers (config → nomad → deploy → patch), test each layer, and keep the codebase dissertation-friendly.

---

## 0) Tech choices (recommended)
- CLI: **Typer** (nice UX, type hints)
- HTTP: **httpx** (TLS options, timeouts, clean API)
- Config files: **tomlkit** (preserves formatting) + **PyYAML** (repo-level defaults)
- Templates: **Jinja2** (render Nomad job JSON or HCL; recommend JSON job specs)
- Models: **pydantic** (optional, but great for typed config/specs)
- Tests: **pytest**

---

## 1) Directory structure

```
fedctl/
  pyproject.toml
  README.md
  LICENSE
  .gitignore
  src/
    fedctl/
      __init__.py
      __main__.py
      cli.py

      config/
        __init__.py
        paths.py
        schema.py
        io.py
        merge.py

      nomad/
        __init__.py
        client.py
        endpoints.py
        errors.py
        models.py

      project/
        __init__.py
        flwr_inspect.py
        pyproject_patch.py
        dockerfile_gen.py

      deploy/
        __init__.py
        spec.py
        naming.py
        render.py
        submit.py
        resolve.py
        status.py
        destroy.py

      state/
        __init__.py
        manifest.py
        store.py

      util/
        __init__.py
        console.py
        retry.py
        subprocess.py
        validators.py

  templates/
    nomad/
      superlink.json.j2
      supernode.json.j2

  tests/
    test_config_merge.py
    test_naming.py
    test_render.py
    test_pyproject_patch.py
    test_nomad_client_smoke.py

  docs/
    cli_spec.md
    nomad_api_mvp.md
```

---

## 2) What each part does (module-by-module)

### 2.1 Entry points

#### `src/fedctl/__main__.py`
- Allows running:
  - `python -m fedctl`
- It typically just imports and runs `cli.app()`.

#### `src/fedctl/cli.py`
- The Typer application definition:
  - defines commands (`ping`, `discover`, `deploy`, `configure`, `status`, `destroy`, `run`)
  - defines **global options** (profile, endpoint override, namespace override, TLS flags)
- This file should be thin: parse CLI → call “service” functions.

**Why:** CLI code gets messy fast. Keep it a router, not the brain.

---

### 2.2 Configuration layer (`fedctl/config/`)

This layer answers: **“How does fedctl know where the cluster is and what defaults to use?”**

#### `paths.py`
- Provides OS-correct paths:
  - `~/.config/fedctl/config.toml`
  - state dir: `~/.local/share/fedctl/`
- One place to change path rules.

#### `schema.py`
- Typed models for config:
  - `ProfileConfig(endpoint, namespace, tls_ca, tls_skip_verify, hint)`
  - `FedctlConfig(active_profile, profiles, state_dir)`
- If you use pydantic, validation happens here.

#### `io.py`
- Load/save config TOML.
- Responsibilities:
  - `load_user_config()`
  - `save_user_config()`
  - never handles secrets beyond reading env var presence

#### `merge.py`
- Merges settings from:
  1) user config profile
  2) environment variables overrides
  3) CLI overrides
- Produces a final “effective runtime config” used by Nomad client.

**Why split io vs merge:** makes it easy to test and reason about precedence rules.

---

### 2.3 Nomad API layer (`fedctl/nomad/`)

This layer answers: **“How do we talk to Nomad over HTTP safely?”**

#### `client.py`
- A small wrapper around httpx:
  - sets base URL
  - injects headers (`X-Nomad-Token`, `X-Nomad-Namespace`)
  - handles TLS parameters
  - applies timeouts
- Exposes methods like:
  - `get(path, params=None)`
  - `post(path, json=None)`
  - `delete(path, params=None)`

You want the rest of your code to avoid raw HTTP details.

#### `endpoints.py`
- Just string constants / helper functions:
  - `STATUS_LEADER = "/v1/status/leader"`
  - `NODES = "/v1/nodes"`
  - `JOB(job_name) = f"/v1/job/{job_name}"`
  - `JOB_ALLOCS(job_name) = f"/v1/job/{job_name}/allocations"`
  - `ALLOC(alloc_id) = f"/v1/allocation/{alloc_id}"`

This avoids magic strings scattered everywhere.

#### `errors.py`
- Domain-specific exceptions:
  - `NomadAuthError`
  - `NomadNotFoundError`
  - `NomadConflictError`
  - `NomadServerError`
- The client maps HTTP statuses into these.

#### `models.py` (optional but helpful)
- Typed parsing of responses you care about:
  - Node summary model (Name, ID, Status, Class)
  - Allocation model (ClientStatus, TaskStates, Resources)
  - Job alloc summary model

**MVP note:** you can start with dicts, but models improve reliability quickly.

---

### 2.4 Project inspection & mutation (`fedctl/project/`)

This layer answers: **“What does the user’s Flower project look like, and how do we modify it safely?”**

#### `flwr_inspect.py`
- Reads `pyproject.toml` and extracts:
  - `[tool.flwr.app]` publisher
  - `[tool.flwr.app.components]` serverapp/clientapp paths
  - `[tool.flwr.app.config]` useful defaults (rounds, etc.)
- Used to validate “this is a Flower app repo”.

#### `pyproject_patch.py`
- Adds/updates federation stanza:
  - `[tool.flwr.federations.remote-deployment]`
- Requirements:
  - idempotent (safe to run multiple times)
  - preserves formatting and comments (use `tomlkit`)
  - optional backup creation
- Exposes:
  - `ensure_federation(path, name, address, insecure, backup=True)`

#### `dockerfile_gen.py`
- Generates your canonical Dockerfile into a temp dir or `.fedctl/`.
- Used by `fedctl build` or `fedctl run`.

---

### 2.5 Deployment pipeline (`fedctl/deploy/`)

This is the heart of fedctl. It answers: **“How do we turn a user repo + constraints into running Nomad jobs?”**

#### `spec.py`
Defines a structured **DeploySpec** (loaded from CLI + repo defaults):
- `exp_name`
- `image_ref`
- `clients`
- `server_port`
- constraints:
  - `superlink_constraint` (e.g., management node)
  - `clients_constraint` (e.g., pi/jetson)
- resources:
  - cpu/mem
- networking mode
- artifact directory

This object is what all deploy functions accept.

#### `naming.py`
- Pure functions to generate consistent names:
  - job names: `fedctl-{namespace}-{exp}-superlink`
  - allocation labels
- Also validates legal Nomad name characters.

**Why separate:** easy testing, avoids subtle naming drift.

#### `render.py`
- Renders Jinja templates into Nomad job JSON.
- Inputs:
  - DeploySpec + namespace + computed names
- Output:
  - two dicts representing job specs (superlink, supernode)

This module should not do any HTTP or filesystem writes—only rendering.

#### `submit.py`
- Calls Nomad API:
  - `POST /v1/jobs` for each job
- Handles:
  - retries on transient failures
  - surfacing useful errors on 403/500

#### `resolve.py`
- Waits for allocations to become running:
  - `GET /v1/job/<job>/allocations`
  - `GET /v1/allocation/<alloc_id>`
- Extracts the **SuperLink port/address**.
- Logic should prefer stable address patterns:
  - if pinned management hostname is known → use that + port
  - else fall back to allocation/node resolution

Outputs something like:
- `FederationAddress(host="nomad.lab.domain", port=27738)`

#### `status.py`
- Implements `fedctl status`:
  - lists allocs for jobs
  - summarizes running/failed counts
  - restart counts if available

#### `destroy.py`
- Implements `fedctl destroy`:
  - deregisters jobs in correct order
  - supports purge option

---

### 2.6 State management (`fedctl/state/`)

This layer answers: **“How do we remember what we deployed so later commands can operate?”**

#### `manifest.py`
Defines schema for a DeploymentManifest:
- exp name
- namespace, endpoint used
- job names
- alloc ids (especially superlink alloc id)
- federation address (host:port)
- timestamps
- image ref + inputs used

#### `store.py`
- Loads/saves manifests from the state dir:
  - `${state_dir}/{namespace}/deployments/{exp}.json`
- Also provides:
  - list deployments
  - delete manifest on destroy

This is how `fedctl address/status/destroy` work without re-deriving everything.

---

### 2.7 Utilities (`fedctl/util/`)

These are shared helpers to keep code clean.

#### `console.py`
- Pretty printing / tables
- consistent error formatting
- `--json` handling helpers

#### `retry.py`
- simple retry wrapper with exponential backoff for:
  - polling allocations
  - transient HTTP 500s

#### `subprocess.py`
- wrappers for calling:
  - `docker build`, `docker push`
- consistent logging and error capture

#### `validators.py`
- validate:
  - endpoint URL
  - exp name
  - image ref
  - federation name

---

## 3) Templates (`templates/nomad/`)

### `superlink.json.j2`
- A Nomad Job JSON template for SuperLink.
- Includes:
  - `constraint` to pin to management node
  - `network` stanza exposing fixed port `27738` (recommended)
  - Docker image `flwr/superlink:<version>` (or your choice)
  - env vars / args

### `supernode.json.j2`
- A Nomad Job JSON template for SuperNodes.
- Includes:
  - `count = clients`
  - constraints for device classes (pi/jetson)
  - Docker image `flwr/supernode:<version>`
  - args pointing at SuperLink address

**Why JSON templates not HCL:** easier to submit directly to `/v1/jobs` without calling `nomad job run`.

---

## 4) Tests (`tests/`)

Start with tests that protect the tricky parts:

- `test_pyproject_patch.py`
  - ensures federation stanza is inserted + idempotent
- `test_render.py`
  - ensures template render produces valid required fields
- `test_naming.py`
  - ensures naming is consistent and safe
- `test_config_merge.py`
  - ensures precedence rules work
- `test_nomad_client_smoke.py`
  - optionally hits a mocked server (httpx mock) to validate headers/TLS options

---

## 5) Suggested `pyproject.toml` for fedctl itself

Dependencies (approx):
- `typer`
- `httpx`
- `tomlkit`
- `pyyaml`
- `jinja2`
- `pydantic` (optional)
- `rich` (optional for tables)
- `pytest` (dev)

---

## 6) How the modules connect (call flow)

### `fedctl run . --name demo --clients 4`
1. `cli.py` parses flags, loads config/profile
2. `config.merge` produces effective runtime config
3. `project.flwr_inspect` validates repo + reads metadata
4. (optional) `project.dockerfile_gen` + `util.subprocess` builds/pushes image
5. `deploy.spec` constructed from CLI + `.fedctl/fedctl.yaml`
6. `deploy.render` produces job json
7. `deploy.submit` POSTs jobs to Nomad
8. `deploy.resolve` polls until superlink is running, returns address
9. `state.store` writes manifest
10. `project.pyproject_patch` writes federation stanza
11. `cli.py` prints: `flwr run . remote-deployment --stream`

---

## 7) What to implement first (MVP priority order)

1) config + ping (`config/*`, `nomad/client.py`, `cli ping`)
2) discover (`GET /v1/nodes`)
3) deploy dry-run (`deploy/spec`, `deploy/render`, templates)
4) deploy real (`deploy/submit`, `deploy/resolve`, `state/store`)
5) configure pyproject (`project/pyproject_patch.py`)
6) destroy/status (`deploy/destroy`, `deploy/status`)

# fedctl repo skeleton (current codebase)

*Updated: 2026-01-20*

This layout mirrors the implemented modules and responsibilities, with brief
notes on what each module owns.

---

## Top-level

```
pyproject.toml          # packaging + entrypoints
.fedctl/                # local config defaults (yaml)
templates/nomad/        # Jinja job templates
rendered/               # example rendered jobs (non-authoritative)
tests/                  # pytest suite
src/fedctl/
  __init__.py           # package marker
  __main__.py           # python -m fedctl entry
  cli.py                # CLI entrypoint + command wiring
  build/
  commands/
  config/
  deploy/
  nomad/
  project/
  state/
  util/
```

Responsibilities:
- `src/fedctl/` — core Python package and CLI
- `src/fedctl/commands/` — CLI subcommand implementations
- `src/fedctl/deploy/` — render/plan/submit/destroy Nomad jobs
- `src/fedctl/build/` — SuperExec image inspection/build/push
- `src/fedctl/project/` — Flower project inspection + pyproject patching
- `src/fedctl/config/` — config loading, schema, and repo defaults
- `src/fedctl/nomad/` — Nomad HTTP client and node views
- `src/fedctl/state/` — deployment manifest persistence
- `src/fedctl/util/` — small shared helpers (console formatting)
- `templates/nomad/` — Jinja job templates used by deploy
- `rendered/` — example rendered output for reference
- `tests/` — pytest suite

---

## Commands (`src/fedctl/commands/`)

- `__init__.py` — command registry exports
- `address.py` — resolve SuperLink control address
- `build.py` — build SuperExec image
- `configure.py` — patch `pyproject.toml`
- `deploy.py` — render + submit jobs
- `destroy.py` — stop jobs for an experiment (or all)
- `discover.py` — list Nomad nodes
- `doctor.py` — connectivity checks
- `inspect.py` — project inspection
- `local.py` — local Nomad harness
- `ping.py` — quick leader check
- `register.py` — bootstrap user registration
- `run.py` — end-to-end build/deploy/configure/run
- `status.py` — alloc status for experiment(s)

---

## Deploy (`src/fedctl/deploy/`)

- `__init__.py` — deploy API exports
- `errors.py` — deploy-specific exception types
- `spec.py` — DeploySpec with namespace + experiment
- `naming.py` — job/service naming helpers (exp-prefixed)
- `render.py` — render Nomad JSON from Jinja templates
- `submit.py` — submit jobs
- `plan.py` — read Nomad plan (dry-run) output
- `resolve.py` — resolve SuperLink allocation/IP/port
- `status.py` — summarize allocations per job
- `destroy.py` — destroy experiment jobs

Templates:
- `templates/nomad/superlink.json.j2`
- `templates/nomad/supernodes.json.j2`
- `templates/nomad/superexec_serverapp.json.j2`
- `templates/nomad/superexec_clientapp.json.j2`

---

## Build (`src/fedctl/build/`)

- `__init__.py` — build API exports
- `inspect.py` — project inspection for build
- `dockerfile.py` — deterministic SuperExec Dockerfile
- `build.py` — docker build invocation
- `tagging.py` — default image tags
- `state.py` — latest build metadata
- `push.py` — optional docker push
- `errors.py` — build-specific exception types

---

## Project (`src/fedctl/project/`)

- `__init__.py` — project API exports
- `flwr_inspect.py` — validate Flower project + read metadata
- `pyproject_patch.py` — patch federations in `pyproject.toml`
- `errors.py` — project-specific exception types

---

## Nomad (`src/fedctl/nomad/`)

- `__init__.py` — Nomad API exports
- `client.py` — HTTP client + endpoints
- `nodeview.py` — node listing helpers / views
- `errors.py` — error types

---

## Config (`src/fedctl/config/`)

- `__init__.py` — config API exports
- `paths.py` — config path resolution
- `io.py` — load/save TOML config
- `schema.py` — config models
- `merge.py` — effective config with overrides
- `repo.py` — repo-local defaults + discovery

---

## State (`src/fedctl/state/`)

- `__init__.py` — state API exports
- `manifest.py` — deployment manifest model
- `store.py` — read/write manifest per namespace+experiment
- `errors.py` — state-specific exception types

---

## Util (`src/fedctl/util/`)

- `console.py` — Rich table helper

---

## Tests (`tests/`)

Key tests:
- `test_config.py`
- `test_deploy_render.py`
- `test_deploy_submit_resolve.py`
- `test_discover.py`
- `test_flwr_inspect.py`
- `test_local.py`
- `test_nomad_client.py`
- `test_ping.py`
- `test_pyproject_patch.py`
- `test_smoke.py`
- `test_state_store.py`

# fedctl repo skeleton (current codebase)

*Updated: 2026-01-20*

This layout mirrors the implemented modules and responsibilities.

---

## Top-level

```
pyproject.toml
src/fedctl/
  __main__.py
  cli.py
  commands/
  config/
  deploy/
  build/
  nomad/
  project/
  state/
  util/
templates/nomad/
tests/
```

---

## Commands (`src/fedctl/commands/`)

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

- `spec.py` — DeploySpec with namespace + experiment
- `naming.py` — job/service naming helpers (exp-prefixed)
- `render.py` — render Nomad JSON from Jinja templates
- `submit.py` — submit jobs
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

- `inspect.py` — project inspection for build
- `dockerfile.py` — deterministic SuperExec Dockerfile
- `build.py` — docker build invocation
- `tagging.py` — default image tags
- `state.py` — latest build metadata
- `push.py` — optional docker push

---

## Project (`src/fedctl/project/`)

- `flwr_inspect.py` — validate Flower project + read metadata
- `pyproject_patch.py` — patch federations in `pyproject.toml`

---

## Nomad (`src/fedctl/nomad/`)

- `client.py` — HTTP client + endpoints
- `errors.py` — error types

---

## Config (`src/fedctl/config/`)

- `paths.py` — config path resolution
- `io.py` — load/save TOML config
- `schema.py` — config models
- `merge.py` — effective config with overrides

---

## State (`src/fedctl/state/`)

- `manifest.py` — deployment manifest model
- `store.py` — read/write manifest per namespace+experiment

---

## Util (`src/fedctl/util/`)

- `console.py` — Rich table helper

---

## Tests (`tests/`)

Key tests:
- `test_deploy_render.py`
- `test_deploy_submit_resolve.py`
- `test_flwr_inspect.py`
- `test_pyproject_patch.py`
- `test_state_store.py`

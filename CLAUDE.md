# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is fedctl

fedctl is a Python CLI for building, deploying, and running Flower federated learning experiments on a Nomad cluster. It has two layers:

- `src/fedctl/` — generic control plane (build Docker images, render/submit Nomad jobs, manage submissions)
- `apps/fedctl_research/` — dissertation Flower app (methods, tasks, experiment configs, repo-config templates)

The key design boundary: **experiment config** = scientific definition of the run; **repo config** = deployment definition of the run. This keeps model/method comparisons separate from placement and network conditions.

## Build and test commands

```bash
uv sync                    # install dependencies (uses uv.lock)
pytest tests/              # run all tests
pytest tests/test_config.py::test_load_config_creates_default_profile -v  # single test
```

There is no linter or formatter configured in pyproject.toml.

## Architecture

### CLI structure

Entry point: `fedctl.cli:app` (Typer). The main app uses `OrderedHelpTyperGroup` for custom help ordering. Sub-apps: `submit_app`, `config_app`, `profile_app`, `local_app`.

Primary user-facing commands: `submit run`, `submit status/logs/results/ls`, `run` (combined build+deploy+run), `destroy`, `local up/down`, `profile`.

### Core modules in `src/fedctl/`

- **config/** — Profile-based config from `$XDG_CONFIG_HOME/fedctl/config.toml`. Precedence: CLI flags > env vars > profile > defaults. Key env vars: `NOMAD_TOKEN`, `NOMAD_ADDR`, `FEDCTL_IMAGE_REGISTRY`, `FEDCTL_PROFILE`.
- **commands/** — Each file maps to a CLI command. The command functions are named `run_<command>`.
- **build/** — Docker image building/pushing, project inspection (parses `pyproject.toml`), semantic tagging.
- **deploy/** — Nomad job rendering via Jinja2 templates (`templates/nomad/*.json.j2`), submission to Nomad HTTP API, placement planning, network emulation (netem). Core types: `DeploySpec`, `SuperLinkSpec`, `SuperNodesSpec`.
- **nomad/** — `NomadClient` wraps httpx with auth headers for the Nomad HTTP API.
- **submit/** — `SubmitServiceClient` talks to the submit service. Handles artifact upload to S3.
- **project/** — `ExperimentConfig` and `FlwrConfig` for parsing experiment TOML and Flower project metadata.
- **state/** — Local state in `.fedctl/state/`. Tracks submission records and build metadata as JSON.

### Submit service (`submit_service/`)

Separate FastAPI application for job queuing with SQLite persistence. Has its own `requirements.txt`.

### Templates

Jinja2 templates in `templates/nomad/` render Nomad job JSON specs: `superlink.json.j2`, `supernodes.json.j2`, `superexec_serverapp.json.j2`, `superexec_clientapp.json.j2`.

## Testing patterns

- Tests use `monkeypatch` + `tmp_path` for environment isolation
- CLI tests use `typer.testing.CliRunner`
- External calls (Nomad, S3, HTTP) are mocked
- Each module has custom error classes in its `errors.py`

## Naming conventions

- Nomad job names: `experiment-<name>` (lowercase, hyphens)
- Service names: `superlink-serverappio-<exp>`, `supernode-clientappio-<exp>-<idx>`
- Node classes: `"link"`, `"node"`, `"submit"`

## Commit style

Imperative, action-first, no conventional-commits prefix. Examples: "Fix truncated Nomad service name sanitization", "Include regime in submit experiment names", "Avoid submit experiment name collisions".

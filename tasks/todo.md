# Task Tracker

## Usage

- Keep this file short and task-focused.
- Put durable architecture, decisions, and constraints in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/context.md`.
- Put reusable corrective rules in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/lessons.md`.
- Archive completed detail in git history instead of leaving long task logs here.

## Active

- [x] Move artifact presign TTL control to submit-service config instead of client-side hardcoded defaults.
- [x] Narrow SuperExec image hashing to project code inputs so experiment-config changes do not churn tags.
- [ ] Redeploy the submit service so live queue accounting uses the revised experiment-side resource values.
- [ ] Reseed the submit image so `submit run` renders Nomad jobs with the revised runtime resource values.
- [ ] Verify one live submission shows the expected `Resources` and matching queue accounting.

## Recent Decisions

- `tasks/context.md` is now the canonical project-memory document.
- Submit-service queue gating for `allow_oversubscribe: false` reserves whole compute nodes, not just CPU/memory slices.
- Blocked reasons should be user-facing and report all unsatisfied typed compute-node bundles.
- Experiment-side queue reservations derive `superexec_clientapp`, `superexec_serverapp`, and `superlink` resources from repo config, with legacy fallbacks matching deploy defaults.
- Actual Nomad runtime resources flow from the same repo-config keys instead of staying hardcoded in deploy spec defaults.
- Active compute-main resource targets now reserve enough capacity for two `supernode + clientapp` bundles per `rpi4` while leaving explicit headroom.
- Default submit experiment names stay short: `task-method-n<nodes>-seed<seed>`.
- SuperExec image hashing now prefers project-local `pyproject.toml` plus `src/`, along with rendered Dockerfile contents and Flower version, instead of hashing the full build context tree.
- Artifact presign TTL is now intended to be server-managed through submit-service environment config, with the client omitting `expires` unless explicitly overridden.

## Review

- Raised active compute-main resources to:
  - `supernode = 1000 CPU / 1024 MiB`
  - `superexec_clientapp = 2000 CPU / 2048 MiB`
  - `superexec_serverapp = 2000 CPU / 2048 MiB`
  - `superlink = 1000 CPU / 1024 MiB`
- On `rpi4` totals `7200 CPU / 7820 MiB`, two compute bundles now use `6000 CPU / 6144 MiB`, leaving `1200 CPU / 1676 MiB` spare.
- On an `rpi5` link host, `superlink + superexec_serverapp` now uses `3000 CPU / 3072 MiB`, leaving ample headroom.

## Verification Shortcuts

- Dispatcher checks:
  - `python3 -m py_compile submit_service/app/workers/dispatcher.py submit_service/tests/test_dispatcher.py`
  - `./.venv/bin/pytest submit_service/tests/test_dispatcher.py -q`
- Deploy checks:
  - `./.venv/bin/pytest tests/test_repo_config_resolution.py tests/test_deploy_render.py -q`
- Research app regression checks:
  - `./.venv/bin/pytest tests/test_experiment_config.py tests/test_dissertation_app.py -q`

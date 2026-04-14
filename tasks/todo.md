# Task Tracker

## Usage

- Keep this file short and task-focused.
- Put durable architecture, decisions, and constraints in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/context.md`.
- Put reusable corrective rules in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/lessons.md`.
- Archive completed detail in git history instead of leaving long task logs here.

## Active

- [ ] Redeploy the submit service so the live dispatcher uses strict whole-node queue reservations and the new `compute-node:*` blocked-reason wording.
- [ ] Verify live `fedctl submit status` shows combined blocked reasons for both `rpi4` and `rpi5` when strict typed capacity is unavailable.

## Recent Decisions

- `tasks/context.md` is now the canonical project-memory document.
- Submit-service queue gating for `allow_oversubscribe: false` reserves whole compute nodes, not just CPU/memory slices.
- Blocked reasons should be user-facing and report all unsatisfied typed compute-node bundles.
- Default submit experiment names stay short: `task-method-n<nodes>-seed<seed>`.
- Default submit-mode image tags are deterministic content hashes: `ctx-<hash>`.
- FIARSE now uses sparse full-model masking with `fiarse-threshold-mode`; `fiarse-selection-mode` was removed.

## Verification Shortcuts

- Dispatcher checks:
  - `python3 -m py_compile submit_service/app/workers/dispatcher.py submit_service/tests/test_dispatcher.py`
  - `./.venv/bin/pytest submit_service/tests/test_dispatcher.py -q`
- Submit naming checks:
  - `./.venv/bin/pytest tests/test_submit_artifact.py tests/test_deploy_render.py -q`
- Research app regression checks:
  - `./.venv/bin/pytest tests/test_experiment_config.py tests/test_dissertation_app.py -q`

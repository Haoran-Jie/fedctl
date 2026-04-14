# Lessons

## Core Working Rules

- Read `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/context.md` and this file before non-trivial work.
- Keep `tasks/context.md` for durable project memory, `tasks/todo.md` for active work, and `tasks/lessons.md` for reusable corrective rules.
- Verify behavior, not just syntax. Prefer focused tests, live logs, and real deployment checks.
- When a checked-in Ansible path exists, use it instead of ad hoc operational steps.
- Do not relax ignore rules for `tasks/` or `apps/fedctl_research/experiment_configs/` without explicit confirmation; if tracked files under ignored paths need committing, use targeted `git add -f` instead.
- `.gitignore` does not untrack files that are already committed; to keep `tasks/` local-only, remove them with `git rm --cached` and only rewrite history if you explicitly want old commits purged.

## Deployment and Submit

- If a submit-time stack trace points into `/usr/local/lib/python3.11/site-packages/fedctl/...`, reseed `fedctl-submit:latest` before assuming the local fix is live.
- For cluster registry pushes, prefer the registry-host path over laptop Docker insecure-registry workarounds.
- Distinguish the explicit repo config used by `submit run` from the default/profile config used by `submit status` and `submit logs`.
- Before assuming an environment variable is already wired in Ansible, check both `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/group_vars/submit_service.yml` and `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/roles/submit_service/templates/fedctl-submit.env.j2`.
- For submit-service queue gating, `allow_oversubscribe: false` must reserve whole experiment nodes, not just subtract CPU/memory.
- User-facing blocked reasons should describe actual queue semantics. Prefer `compute-node:*` over internal terms like `node-bundle`.

## Methods and Experiments

- Keep dissertation methods first-class in the repo surface; do not hide distinct methods behind another method's ablation flag.
- Remove config knobs that no longer change real behavior.
- For exact-capacity placements, test the boundary count; indexing bugs often hide until full-capacity runs.
- For long experiment batches, prefer `--no-stream` plus status polling over fragile interactive streaming loops.
- Interpret method rankings against the actual experiment regime; literature expectations do not automatically transfer to short IID full-participation runs.

## Docs and Writeup

- Reuse established formatting and repo conventions exactly when possible.
- Organize repo and writeup structure around the evaluation story, not implementation history.
- Prefer plain naming such as `plan`, `study`, or `experiment family` unless the user asks for something else.
- When repo docs and operational state disagree, verify the live system before answering.

# Lessons

- When matching dissertation formatting or repo conventions, reuse the exact existing definition first; do not approximate with a fallback unless there is a verified blocker.
- When assessing network-cause confidence, distinguish between strong operational evidence and a literal 100% guarantee; cached routes and partial checks are not the same as a full post-removal revalidation.
- When naming docs or study groupings, prefer plain terms like `plan`, `study`, or `experiment family`; avoid grander labels unless the user explicitly wants them.

- When the repo folder hierarchy is part of the dissertation story, organize it around the evaluation structure from the writeup instead of around implementation history or method names.
- When a literature method is conceptually distinct in the dissertation, expose it as a first-class method in the repo surface instead of hiding it behind another method's ablation flag.
- When the user asks for theorem treatment in the writeup, use actual numbered theorem or lemma environments grounded in the cited literature; styled prose callouts are not a substitute.
- When defining reusable `tcolorbox` environments with optional arguments, pass optional keys through as `#1`; do not wrap them again as `title=#1` if call sites already provide `title=...`.
- When placing long theorem bounds inside dissertation callout boxes, default to multiline `aligned` displays instead of one-line equations; box width must be treated as a real layout constraint.
- When repo docs and inventory comments disagree about control-plane placement, verify the live service state on the candidate hosts before answering; do not rely on one stale file.
- When discussing current cluster networking, verify `ansible/group_vars/all.yml` before reasoning from older Wi-Fi-first behaviour; the active dissertation cluster defaults are Ethernet-first with `network_prefer_wifi: false`.
- When changing the inventory addressing model, update every dependent default that assumed `ansible_host` meant a specific network, then verify with a real `ansible -m ping` against the new primary path instead of stopping at syntax-check.
- When restoring a node into the campus-IP inventory, use the registered campus address rather than carrying forward an older private-LAN address from a previous setup.
- When a user says the network path has changed and a previously blocked campus address should now be reachable, re-test that path immediately and switch the deployment workflow back to the primary network instead of continuing to optimize around the earlier fallback constraint.
- When debugging a Flower submission that spawns transient Nomad jobs, preserve them with the no-destroy path before chasing logs; otherwise the real failing server/client allocations can disappear before inspection.
- When the user asks to debug why a run failed, do not pivot to readiness or next-run advice after partial success; follow the failing path to a verified root cause and fix it first.
- When the user asks for a summary of experiments or runs, default to documentation or an answer in the thread; do not add a new CLI/reporting feature unless they explicitly ask for tooling.
- When summarizing the dissertation run queue, verify that the documented main-study methods exactly match the intended method set in the experiment tree; do not silently drop a first-class method like `fedstaleweight`.
- When defining headline-study data caps, distinguish between a real resource cap and a scientific design choice; for balanced IID main studies, prefer the natural equal-split per-client dataset size over device-specific caps that introduce extra quantity skew.
- When turning the approved run matrix into `tasks/todo.md`, enumerate every remaining pilot method in execution order before marking the next phase started; do not skip compute-main methods like `fedrolex` or `fiarse` just because a later network pilot has already run.
- When batching long experiment submissions in a shell loop, do not rely on `fedctl submit run --stream`; use `--no-stream`, capture the submission ID, and poll terminal status instead because the stream path is interactive and fragile across disconnects.
- When changing requested supernode counts to exactly match live inventory, run a focused placement-path test; planner code that mixes 1-based instance indices with 0-based arrays can pass smaller configs and only fail at the exact-capacity boundary.

## Utility Commands

- Purge finished experiment jobs from the Nomad server without touching control-plane services:

```bash
ssh rpi@128.232.61.111 '
nomad status | awk "NR>1 && \$1 ~ /^(fp-|cm-|nm-|u5-|smoke-)/ {print \$1}" |
while read -r job; do
  [ -n "$job" ] || continue
  nomad job stop -purge "$job"
done
'
```

- For a single experiment prefix, narrow the match instead of purging every experiment family:

```bash
ssh rpi@128.232.61.111 '
nomad status | awk "NR>1 && \$1 ~ /^fp-e-c10-seed1338-/ {print \$1}" |
while read -r job; do
  [ -n "$job" ] || continue
  nomad job stop -purge "$job"
done
'
```

## 2026-04-13
- If a submit-time stack trace points into `/usr/local/lib/python3.11/site-packages/fedctl/...` inside the submit runner, verify whether the local workspace fix has also been rebuilt into `fedctl-submit:latest` before asking the user to retry.
- For registry-seeded images, use the documented forced seed command when code changed but the tag remains `latest`; a plain rerun will keep using the stale image.
- If `docker buildx build --push` fails with `http: server gave HTTP response to HTTPS client`, do not ask the user to configure their laptop Docker daemon first; move the build/push onto the registry host or otherwise use the cluster's insecure-registry path directly.
- If the submit runner image must reflect a code fix, commit and push it first, then rebuild from a git checkout on the registry host. Avoid staging the whole workspace unless the fix is intentionally unpushed and the copy cost is acceptable.
- For exact-allocation experiments, do not make capability discovery depend on repeated retries against live nodes; prefer one-shot discovery plus an explicit deploy-plan fallback, because retry loops can stall startup even when the cluster inventory is otherwise correct.
- `allow_oversubscribe: false` is only a deploy-time placement rule; it does not serialize queued submissions. If the user wants "job B waits until job A is completed", implement that in the submit-service dispatcher by reserving node capacity for active submissions before dispatching the queue.
- When the repo already has an Ansible role for service deployment, do not fall back to ad hoc SSH/systemd restart instructions as the primary path; commit, push, and use the checked-in playbook.

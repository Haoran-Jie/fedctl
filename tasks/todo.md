
# Submit Dispatcher Reservation Debug Plan

- [x] Inspect the current dispatcher reservation logic and confirm the intended non-oversubscribe queue behavior.
- [x] Inspect the live submit-service state on `rpi5-024` and the active concurrent submissions.
- [x] Identify the root cause for concurrent 20-node dispatch and implement the fix.
- [ ] Verify the dispatcher locally and confirm the live service is running the corrected code.

## Review

- Verified on `rpi5-024` that the submit-service is running in `queue` mode and the concurrent submissions in the live SQLite state both carry `--supernodes rpi4=10 --supernodes rpi5=10 --no-allow-oversubscribe`, so the issue is not stale deployment or missing queue metadata.
- Queried the live `/v1/nodes` inventory and confirmed the same `rpi4`/`rpi5` nodes are hosting allocations from both active 20-node experiments at once. Nomad still reports spare CPU and memory on those nodes, which explains why the old dispatcher logic incorrectly let the second submission through.
- Root cause: `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service/app/workers/dispatcher.py` treated `allow_oversubscribe: false` as a strict CPU/memory check only. That semantics is too weak for experiment queueing because a node can still have spare resources while already being reserved by another active experiment.
- Fixed `_reserve_strict(...)` so strict node-bundle reservations now consume the entire node for queue gating instead of only decrementing the requested bundle resources. This matches the intended meaning of `allow_oversubscribe: false` for experiment scheduling.
- Added a regression in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service/tests/test_dispatcher.py` that models the live condition: each node has enough free CPU/memory for two bundles, but a queued second 20-node submission must still be blocked once a first strict 20-node submission is running.
- Verification:
  - `python3 -m py_compile submit_service/app/workers/dispatcher.py submit_service/tests/test_dispatcher.py`
  - `./.venv/bin/pytest submit_service/tests/test_dispatcher.py -q`
  - result: `7 passed`


# FIARSE Global Threshold Fix Plan

- [x] Inspect the current FIARSE global-threshold implementation and existing slicing tests.
- [x] Change global thresholding to rank channels by raw magnitude across layers.
- [x] Add a targeted regression proving low-magnitude outliers are not selected over larger-magnitude channels.
- [x] Verify the slicing module and targeted test file locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/fiarse/slicing.py` so `threshold_mode = "global"` now ranks channels by their raw magnitude scores across layers, which is the intended paper-aligned behavior for a global TopK-style threshold.
- The previous implementation used mean-centered salience in global mode, which could promote unusually small channels simply because they were far from the mean. That is no longer possible.
- Added a focused regression in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_dissertation_app.py` asserting that global thresholding prefers `[100, 99]` over a low outlier `[1]` in a minimal FIARSE slicing example.
- Verification:
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/methods/fiarse/slicing.py tests/test_dissertation_app.py`
  - passed
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - `1 skipped` in this local environment because the test file is gated by `pytest.importorskip("torch")`

# Content-Addressed Image Tagging Plan

- [x] Inspect the current image-tagging path and identify why submit builds churn tags.
- [x] Replace timestamp-based fallback tagging in the shared build path with a deterministic build-context hash.
- [x] Hash the actual image inputs used by build-and-record: filtered context tree bytes plus rendered Dockerfile content and Flower version.
- [x] Add focused tests for deterministic tags and content-sensitive tag changes.
- [x] Verify the tagging path and focused tests locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/build/tagging.py` so the default image tag now prefers a deterministic `ctx-<hash>` suffix computed from the actual build inputs instead of falling back to a timestamp when `.git` is unavailable.
- The content hash covers:
  - the full extracted build context tree passed to Docker
  - the rendered Dockerfile contents
  - the Flower version
- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/commands/build.py` so `build_and_record(...)` passes the build context and rendered Dockerfile into the shared tag generator. This means submit-runner builds from uploaded archives now reuse stable tags when the archive contents are unchanged.
- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_build_registry_override.py` for the expanded tag-generator signature and added new coverage in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_build_tagging.py` proving:
  - identical context + Dockerfile + Flower version yields the same tag
  - changing context bytes changes the tag
  - changing Dockerfile contents changes the tag
- Verification:
  - `python3 -m py_compile src/fedctl/build/tagging.py src/fedctl/commands/build.py tests/test_build_registry_override.py tests/test_build_tagging.py`
  - `./.venv/bin/pytest tests/test_build_registry_override.py tests/test_build_tagging.py -q`
  - result: `4 passed`

# Capability Discovery Log Formatting Plan

- [x] Inspect the capability-discovery logging calls in the shared runtime.
- [x] Align the node and device-type fields with fixed-width formatting for easier vertical scanning in live logs.
- [x] Keep the existing capability payload content unchanged.
- [x] Verify the runtime module and shared dissertation test file locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/runtime.py` so capability-discovery logs now format:
  - `node` as a fixed-width right-aligned field
  - `device_type` as a fixed-width left-aligned field
- The same node-width formatting is now used for capability-discovery error and missing-record lines, so the whole discovery block lines up vertically in the logs.
- This is a log-formatting-only change; the discovery logic and payload contents are unchanged.
- Verification:
  - `python3 -m py_compile apps/fedctl_research/src/fedctl_research/methods/runtime.py`
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - result: `58 passed`

# FIARSE Selection-Mode Cleanup Plan

- [x] Inspect every remaining use of `fiarse-selection-mode` in config, strategy wiring, and tests.
- [x] Remove `fiarse-selection-mode` from the supported config surface and FIARSE strategy wiring.
- [x] Update stale normalization tests that still construct FIARSE configs with `selection-mode`.
- [x] Verify the affected config/runtime files and focused test suites locally.

## Review

- Removed the redundant `fiarse-selection-mode` surface from:
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/config.py`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/pyproject.toml`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/project/experiment_config.py`
- Removed the unused FIARSE strategy plumbing and summary logging from:
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/fiarse/__init__.py`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/fiarse/strategy.py`
- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_experiment_config.py` so the nested normalization fixture reflects the cleaned FIARSE config surface.
- The effective FIARSE knobs are now the ones that actually change behavior:
  - `fiarse-threshold-mode`
  - `fiarse-global-learning-rate`
- Verification:
  - `python3 -m py_compile apps/fedctl_research/src/fedctl_research/config.py apps/fedctl_research/src/fedctl_research/methods/fiarse/__init__.py apps/fedctl_research/src/fedctl_research/methods/fiarse/strategy.py src/fedctl/project/experiment_config.py tests/test_experiment_config.py`
  - `./.venv/bin/pytest tests/test_experiment_config.py -q`
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - results: `10 passed`, `58 passed`

# Nomad Service Naming Plan

- [x] Inspect the Nomad render path and identify whether the failure is due to length, invalid characters, or both.
- [x] Fix the shared service-name helper so rendered Nomad service names are RFC1123-safe.
- [x] Add focused deploy-render coverage for experiment names containing underscores and uppercase characters.
- [x] Verify the naming helper and deploy-render tests locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/deploy/naming.py` so Nomad service names now sanitize the experiment token to lowercase RFC1123-safe labels before applying the existing length-safe truncation/hash logic.
- This fixes the actual failing case from the deploy logs: `cifar10_cnn-fiarse-n20-seed1337-superlink-serverappio` was only 53 characters long, but Nomad rejected it because the underscore in `cifar10_cnn` is not RFC1123-valid for a service name.
- Added focused coverage in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_deploy_render.py` asserting that service names derived from experiment names like `cifar10_cnn-FIARSE-n20-seed1337` are lowercase, underscore-free, and still preserve the expected service suffixes.
- Verification:
  - `python3 -m py_compile src/fedctl/deploy/naming.py tests/test_deploy_render.py`
  - `./.venv/bin/pytest tests/test_deploy_render.py -q`

# Submit Auto-Exp Naming Plan

- [x] Inspect the submit command path and confirm where the experiment name is resolved.
- [x] Generate a default experiment name from the resolved experiment config only when `--exp` is omitted.
- [x] Preserve explicit `--exp` behavior unchanged.
- [x] Add focused submit-command tests for generated-vs-explicit experiment names.
- [x] Verify the submit command module and targeted tests locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/commands/submit.py` so `fedctl submit run` now derives a default experiment name from the resolved experiment config when the user does not pass `--exp`.
- The generated name uses the same compact signature discussed for run naming:
  - `task`
  - `method`
  - node count as `n<k>` from the effective run config
  - `seed<k>` when a single seed is part of the effective run config or CLI invocation
- The generated submit experiment name intentionally omits the capacity-split token so the downstream Nomad job/service names stay within RFC 1123 length limits.
- Explicit `--exp` still wins unchanged; the new logic only applies when `experiment=None`.
- The submit path now treats config parsing/materialization failures as ordinary experiment-config errors instead of letting them escape as an unhandled exception.
- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_submit_artifact.py` with targeted coverage for:
  - omitted `--exp` producing a config-derived experiment name
  - explicit `--exp` overriding that generated name
- Verification:
  - `python -m py_compile src/fedctl/commands/submit.py tests/test_submit_artifact.py`
  - `./.venv/bin/pytest tests/test_submit_artifact.py -q`
  - result: `7 passed`

# W&B Run Naming Plan

- [x] Inspect the current experiment and W&B run naming path.
- [x] Add config-derived run naming fields for task, method, node count, and capacity split.
- [x] Update the W&B logger tests to pin the new naming shape.
- [x] Verify the logger module and tests locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/wandb_logging.py` so W&B run names now append a compact config signature derived from the run config:
  - node count as `n<k>` from `min-available-nodes`/related keys
  - capacity split as `split-<rate>x<pct>_...` from `model-rate-levels` and `model-rate-proportions`
- The canonical key stored in W&B metadata now includes the same `node-count/capacity-split` signature, so retries for the same experimental condition still share one canonical identity while each submission attempt keeps its own distinct run name.
- This change does not override the submit-side experiment name passed with `--exp`; it only makes the W&B run naming and metadata more informative.
- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_wandb_logging.py` to assert the new name and canonical-key format.
- Verification:
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/wandb_logging.py tests/test_wandb_logging.py`
  - `./.venv/bin/pytest tests/test_wandb_logging.py -q`
  - result: `5 passed`

# Submit Queue Reservation Plan

- [x] Inspect the submit-service dispatcher and confirm where queue admission decisions are made.
- [x] Reserve node capacity for active `running` submissions before dispatching queued work.
- [x] Reconcile running submissions before queue dispatch so completed jobs release reservations immediately.
- [x] Add targeted dispatcher tests for block-while-running and release-after-completion behavior.
- [x] Verify the dispatcher module and tests locally.

## Review

- Updated `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service/app/workers/dispatcher.py` so `run_once()` now reconciles `running` submissions first, then reserves capacity for all active submissions before it evaluates queued or blocked candidates.
- The queue gate now treats each requested compute node as a bundled reservation for `supernode + superexec-clientapp` on the corresponding device type. That matches the intended submission-side semantics: once a 20-node experiment is dispatched, those 20 nodes stay busy in the queue until the submission is marked completed/failed/cancelled.
- Added focused coverage in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service/tests/test_dispatcher.py` for:
  - a queued 20-node submission being blocked while a running 20-node submission already holds the same `rpi4/rpi5` capacity
  - the blocked submission dispatching once the earlier submission is completed
- Verification:
  - `python -m py_compile submit_service/app/workers/dispatcher.py submit_service/tests/test_dispatcher.py`
  - `./.venv/bin/pytest submit_service/tests/test_dispatcher.py -q`
  - result: `6 passed`

# Capability Discovery Revert Plan

- [x] Restore the one-shot capability discovery path in `runtime.py`.
- [x] Record the correction in `tasks/lessons.md`.
- [x] Verify the reverted code compiles cleanly.

## Review

- Reverted the retry loop in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/runtime.py` so capability discovery now sends one query batch to all discovered nodes and processes the replies once, matching the previous behavior.
- This keeps the typed device allocation work intact; only the discovery retry behavior was removed.
- Verification:
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/methods/runtime.py`
  - passed

# Per-Client Eval Metrics Plan

- [x] Add a structured per-client evaluation event stream instead of only aggregated round-level client-eval metrics.
- [x] Log per-client eval accuracy/loss/duration/examples for synchronous strategies.
- [x] Add targeted regression coverage and run the available verification commands.

## Review

- Added a new artifact stream `client_eval_events.jsonl` in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/result_artifacts.py`.
- Wired per-client evaluation logging into:
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/fedavg/strategy.py`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/heterofl/strategy.py`
- Each client-eval event now records:
  - `server_step`
  - `node_id`
  - `device_type`
  - `model_rate`
  - `eval_acc`
  - `eval_loss`
  - `eval_duration_s`
  - `num_examples`
- This means the repo now has both:
  - aggregated client-eval metrics in W&B/system logs
  - per-client client-eval metrics in structured artifacts
- Verification:
  - `./.venv/bin/python -m py_compile apps/fedctl_research/src/fedctl_research/result_artifacts.py apps/fedctl_research/src/fedctl_research/methods/fedavg/strategy.py apps/fedctl_research/src/fedctl_research/methods/heterofl/strategy.py tests/test_dissertation_app.py`
  - passed
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - skipped in this local environment because `.venv` does not currently provide `torch`

# Server Eval Timing Instrumentation Plan

- [x] Add explicit `system/round-server-eval-duration-s` logging in the shared server-evaluation path.
- [x] Include the same timing in the structured evaluation artifact payload.
- [x] Add a targeted regression test for the new metric and run the available verification commands.

## Review

- Added `system/round-server-eval-duration-s` in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/runtime.py` inside `central_evaluate_fn(...)`, so the metric is logged consistently for all methods that use the shared centralized server evaluation path.
- Added `round_server_eval_duration_s` to the structured evaluation artifact payload in the same shared runtime hook, so the timing is available both in W&B/system metrics and in `evaluation_events.jsonl`.
- Added a focused regression in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_dissertation_app.py` asserting that centralized evaluation logs the new timing into both the system metrics and artifact payload.
- Verification:
  - `./.venv/bin/python -m py_compile apps/fedctl_research/src/fedctl_research/methods/runtime.py tests/test_dissertation_app.py`
  - passed
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - skipped in this local environment because `torch` is unavailable in `.venv`, so the new test could not execute here

# Singleton A Calibration Plan

- [x] Create a separate tuned singleton-`a` calibration config without overwriting the original interpolation baseline.
- [x] Apply the requested hyperparameter changes: `20` rounds, `3` local epochs, `0.05` learning rate.
- [x] Verify the new config file and provide the exact launch command.

## Review

- Added a separate calibration config at `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/experiment_configs/compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/a_calibration/heterofl.toml` so the original singleton-`a` baseline remains unchanged.
- Applied the requested hyperparameter changes only in that new config:
  - `num-server-rounds = 20`
  - `local-epochs = 3`
  - `learning-rate = 0.05`
- Marked the run distinctly in W&B with a calibration-specific group and tags to avoid mixing it with the original interpolation baseline.
- Verification:
  - `./.venv/bin/pytest tests/test_experiment_config.py -q`
  - result: `10 passed`

# AE interpolation review

- [x] Collect the completed `a_e` run set (`e`, `p001`-`p009`) from W&B and/or submit records.
- [x] Build a compact table with final global accuracy/loss and confirm run completion state.
- [x] Check whether the `a_e` interpolation trend is monotonic or at least directionally increasing as expected.
- [x] Recommend the next experiment step based on the observed curve and paper-faithful plan.

## Review

- Pulled the completed `a_e` interpolation slice from W&B for:
  - `e`
  - `p001` through `p009`
- All ten runs are in `finished` state with final round `20`.
- Final global server accuracy/loss table:
  - `e`: `0.4870`, `1.3933`
  - `p001`: `0.5422`, `1.3381`
  - `p002`: `0.6362`, `1.0175`
  - `p003`: `0.6585`, `0.9661`
  - `p004`: `0.6685`, `0.9342`
  - `p005`: `0.6722`, `0.9251`
  - `p006`: `0.6733`, `0.9194`
  - `p007`: `0.6748`, `0.9163`
  - `p008`: `0.6757`, `0.9100`
  - `p009`: `0.6785`, `0.9059`
- The global `a_e` interpolation curve is strictly monotonic increasing across all ten points. This is stronger than the minimum expected outcome; it means the first paper-faithful interpolation slice behaves exactly in the intended direction on the cluster.
- Runtime was stable across the mixed points (`~1443s` to `~1491s`), while singleton `e` was much faster (`~635s`), which is consistent with the reduced model size.
- The extracted `e`-submodel accuracy decreases as the proportion of `a` clients increases (`0.4870` at singleton `e` down to `0.3326` at `p009`), which is expected because the final global model is being optimized more heavily toward the full-width side of the pair.
- Recommended next step:
  - run singleton `a` to anchor the upper endpoint explicitly
  - then move to the next main-text interpolation families `b_e`, `c_e`, and `d_e`
  - defer the remaining appendix-only pairs until those headline supporting curves are validated

# Submit Log Default Stream Plan

- [x] Inspect why the submission log page defaults to the submit job stderr stream.
- [x] Change the submit-service UI default so a submission opens on the submit job stdout stream instead.
- [x] Preserve explicit log stream selections from query parameters and log-panel form submissions.
- [x] Run targeted submit-service verification and record the result.

## Review

- Changed the UI route defaults in `submit_service/app/routes/ui.py` so both `/ui/submissions/{submission_id}` and `/ui/submissions/{submission_id}/logs` now default `stderr` to `False`. This makes the submission detail page and log panel open on the submit job stdout stream unless the user explicitly selects stderr.
- Updated `submit_service/tests/test_ui.py` so the archived-log coverage now expects stdout on the default page load and still proves that `?stderr=true` keeps the explicit stderr override working.
- Verification:
  - `./.venv/bin/pytest submit_service/tests/test_ui.py -q`
  - blocked during collection because the local `.venv` is missing declared submit-service dependencies: `itsdangerous` and `ansi2html`
  - fallback verification via source parsing confirmed:
    - `submission_detail_page: stderr default = False`
    - `submission_logs_panel: stderr default = False`

# Batch Submit Loop Plan

- [x] Inspect why the interpolation batch loop was fragile with `--stream`.
- [x] Record the batch-submission lesson in the project notes.
- [x] Replace the loop with a batch-safe `--no-stream` variant that waits for terminal submission states.

## Review

- The `fedctl submit run --stream` path is interactive and holds the terminal on a long-lived log stream. That is workable for one run, but it is fragile for unattended shell loops because a dropped stream or terminal disconnect can fail the command even if the remote run itself is still healthy.
- The batch-safe pattern is to submit with `--no-stream`, capture the submission ID, and poll `fedctl submit status` until the run reaches `completed`, `failed`, `cancelled`, or `crashed`.

# Nomad Experiment Cleanup Plan

- [x] List the currently running experiment jobs on `rpi5-024` and isolate them from control-plane services.
- [x] Purge the leftover experiment jobs from the finished interpolation batch.
- [x] Verify that no experiment jobs remain running after the purge.
- [x] Record a reusable Nomad purge utility command in the project notes.

## Review

- Listed the current Nomad job set directly on `rpi5-024` and confirmed that only leftover interpolation jobs with the prefix `fp-e-c10-seed1338-` were still running; no control-plane services were managed by Nomad in that list.
- Purged the full leftover batch from `rpi5-024` with `nomad job stop -purge` for:
  - `fp-e-c10-seed1338-superlink`
  - `fp-e-c10-seed1338-supernodes`
  - `fp-e-c10-seed1338-superexec-serverapp`
  - `fp-e-c10-seed1338-superexec-clientapp-rpi5-1` through `fp-e-c10-seed1338-superexec-clientapp-rpi5-10`
- Verified cleanup by re-running `nomad status` and filtering for experiment prefixes `fp-`, `cm-`, `nm-`, `u5-`, and `smoke-`; the filtered result returned no remaining experiment jobs.
- Recorded reusable cleanup commands in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/lessons.md` for:
  - purging all experiment-family jobs
  - purging a single experiment prefix only

# Paper-Faithful Experiment Plan Revision and Targeted Cleanup

- [ ] Add a new `fixed_pair_interpolation` HeteroFL ablation family to the plan, distinct from the existing dynamic `uniform_five_levels` family.
- [ ] Define the full paper-faithful run matrix:
  - singleton baselines `a`, `b`, `c`, `d`, `e`
  - pairwise families `a-b`, `a-c`, `a-d`, `a-e`, `b-c`, `b-d`, `b-e`, `c-d`, `c-e`, `d-e`
  - fixed-assignment proportion sweep `10/90` through `90/10` for each pair
- [ ] Keep the interpolation family at `10` active logical clients so the supporting-study x-axis matches the paper's `10%` interpolation steps exactly.
- [ ] Present only `a-e`, `b-e`, `c-e`, and `d-e` in the main text; move the full `10`-pair grid to the appendix.
- [ ] Lift `uniform_five_levels` onto the live 12-node main-study footing without changing its dynamic five-level capacity story.
- [ ] Run the `uniform_five_levels` family on the real cluster and inspect submit logs, Nomad status, result artifacts, and W&B coverage.
- [ ] Check whether the recorded metrics are sufficient for the HeteroFL/FedRolex five-level claim; add missing instrumentation only if the current outputs are inadequate.
- [ ] Compare the observed result against the expected paper-faithful direction and record the outcome back into `docs/experiment_plan.md`.
- [ ] Materialize a runnable local repo config for `fixed_pair_interpolation` with live submit and W&B values under `.fedctl/`.
- [ ] Run the first four interpolation pilots:
  - singleton `e`
  - `a_e/p001`
  - `a_e/p005`
  - `a_e/p009`
- [ ] Inspect submit logs, Nomad placement, and final W&B/artifact metrics for those four pilots.
- [ ] Check whether the first interpolation slice is monotonic before scheduling the rest of the `95`-run family.

## In-Progress Review

- Fixed the first `fixed_pair_interpolation` runtime blocker by registering `heterofl-partition-rates = ""` in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/pyproject.toml`. Flower validates run-config keys against `[tool.flwr.app.config]`, so the experiment config key existed locally but was rejected at runtime until it was declared there.
- Fixed the second blocker by restoring a backward-compatible `discover_node_device_types(...)` wrapper in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/runtime.py`. The earlier partition-aware refactor renamed that helper, but `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/src/fedctl_research/methods/fedbuff/async_loop.py` still imported the old symbol, which broke method-registry import at ServerApp startup for unrelated methods too.
- Verification after both fixes:
  - `./.venv/bin/pytest tests/test_experiment_config.py tests/test_dissertation_app.py -q`
  - result: `10 passed, 1 skipped`
- Completed interpolation pilot results so far:
  - `fp-e-c10-seed1337`:
    - W&B run `fp-e-c10-seed1337-heterofl-cifar10_cnn-direct`
    - final server accuracy `0.4870`
    - final server loss `1.3933`
    - final round `20`
  - `fp-ae-p001-c10-seed1337`:
    - W&B run `fp-ae-p001-c10-seed1337-heterofl-cifar10_cnn-direct`
    - final server accuracy `0.5422`
    - final server loss `1.3381`
    - final round `20`
- Current interpretation:
  - the first interpolation step moved in the expected direction (`a_e/p001 > e`)
  - the remaining heavier points `a_e/p005` and `a_e/p009` still need to run before the monotonicity check is complete

- [x] Rewrite `docs/experiment_plan.md` around paper-claim evidence for HeteroFL, FedRolex, FIARSE, FedBuff, and FedStaleWeight.
- [x] Bring `writeup/4_evaluation.tex` into alignment with the live plan, live configs, and the new headline/supporting-study structure.
- [x] Add an explicit evidence matrix to the plan and mirror it in the writeup notes.
- [x] Perform only literal, behavior-preserving cleanup in planning/evaluation/result-summary surfaces.
- [x] Verify doc/config consistency against the current experiment tree and run the relevant unchanged tests.

## Review

- Rewrote `docs/experiment_plan.md` so it is now organized around paper claims and required evidence rather than around config directories alone. Each implemented method now has explicit fields for the original claim, what the paper measures, closest repo families, current coverage, missing coverage, and main-text versus appendix placement.
- Added a compact evidence matrix to `docs/experiment_plan.md` and mirrored it in `writeup/4_evaluation.tex`, making the status of each method explicit as covered versus partial rather than leaving those judgments implicit.
- Replaced the stale Chapter 4 evaluation plan in `writeup/4_evaluation.tex` with the current live settings: balanced `6 x rpi4 + 6 x rpi5`, compute-main `15/20` rounds, network-main `15/20` steps, async concurrency `8`, and the full async method set including `fedstaleweight`.
- Reframed Chapter 4 around two headline studies plus paper-faithful supporting studies for `HeteroFL`, `FedRolex`, `FIARSE`, `FedBuff`, and `FedStaleWeight`, and made the main-text versus appendix split explicit.
- Performed one literal code cleanup in `apps/fedctl_research/src/fedctl_research/result_artifacts.py` by deduplicating the event-path bookkeeping into a small keyed map without changing the logging surface or filenames.
- Updated `apps/fedctl_research/README.md` so the checked-in descriptions no longer claim the main repo-configs are 4-node profiles; it now points scientific readers to `docs/experiment_plan.md` and labels the main presets as 12-node balanced profiles.
- Verification:
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/result_artifacts.py`
  - `./.venv/bin/pytest tests/test_dissertation_app.py tests/test_experiment_config.py -q`
  - `latexmk -xelatex -interaction=nonstopmode -file-line-error main.tex` in `writeup/`
- Result: the unchanged tests passed (`10 passed, 1 skipped`) and the dissertation PDF rebuilt successfully at `writeup/out/main.pdf`. The new evaluation chapter no longer has the previous page-spilling evidence table, though some ordinary overfull-box warnings remain elsewhere in the document.
- Added a concrete remaining-ablation checklist to `docs/experiment_plan.md`, turning the evidence matrix into an execution list with required evidence and minimum dissertation deliverables for each supporting family.
- Updated `writeup/Appendix_FedBuff_Configuration.tex` and `writeup/Appendix_HeteroFL_Configuration.tex` so the appendix configuration chapters now describe the current 12-node balanced headline studies rather than the earlier 4-node baseline wording.
- Added a concrete paper-faithful HeteroFL interpolation design to `docs/experiment_plan.md`: singleton baselines `a-e`, all `10` pair families, and fixed `10%` mixture steps per pair. This now separates the dynamic `uniform_five_levels` table-style study from the fixed-interpolation figure-style study rather than conflating them.
- Chose `10` active logical clients for the interpolation family on purpose. That is a supporting-study design decision to preserve the original paper's exact `10%` x-axis, while the headline studies remain on the full balanced 12-node rack.
- Implemented actual runnable configs for the new `fixed_pair_interpolation` family under `apps/fedctl_research/experiment_configs/compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/cifar10_cnn/`: `5` singleton baselines plus `90` pairwise mixture runs, for `95` `heterofl.toml` files in total.
- Added a matching repo preset at `apps/fedctl_research/repo_configs/compute_heterogeneity/ablations/fixed_pair_interpolation/none.yaml` using `10 x rpi5` so the interpolation study isolates model-size assignment from mixed-hardware bottlenecks and preserves exact `10%` mixture steps.
- Extended the heterogeneous assignment runtime so fixed-rate configs can target logical `partition-id` via `heterofl-partition-rates`, with precedence `node-id > partition-id > device-type > default`. This made the interpolation family representable without baking in unstable runtime node IDs.
- Verification:
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/config.py apps/fedctl_research/src/fedctl_research/methods/assignment.py apps/fedctl_research/src/fedctl_research/methods/runtime.py apps/fedctl_research/src/fedctl_research/methods/heterofl/__init__.py apps/fedctl_research/src/fedctl_research/methods/fedrolex/__init__.py apps/fedctl_research/src/fedctl_research/methods/fiarse/__init__.py apps/fedctl_research/src/fedctl_research/methods/heterofl/strategy.py tests/test_experiment_config.py tests/test_dissertation_app.py src/fedctl/project/experiment_config.py`
  - `./.venv/bin/pytest tests/test_experiment_config.py tests/test_dissertation_app.py -q`
  - Result: `10 passed, 1 skipped`
# Writeup Appendix and FL-Theory Revision Plan

- [x] Add a dedicated notation appendix chapter and move unified notation out of `writeup/Appendix_Algorithms.tex`.
- [x] Improve the pseudocode appendix presentation with clearer method-delta notes, colouring, and reading guidance for related algorithms.
- [x] Expand `writeup/2_preparation.tex` Section 2.3 with stronger FL formalism, method equations, and actual theorem/lemma environments grounded in the scoped literature.
- [x] Verify cross-references and compile-facing LaTeX structure after the rewrite.

## Review

- Added a new dedicated notation chapter at `writeup/Appendix_Notation.tex` and inserted it ahead of the algorithm appendix in `writeup/main.tex`, so notation now has its own appendix chapter rather than being buried inside pseudocode.
- Reworked `writeup/Appendix_Algorithms.tex` into a comparison appendix with a reading-guide box, method-family colouring, and explicit notes about where the related algorithms actually differ.
- Rewrote the `FL Algorithms` section in `writeup/2_preparation.tex` around a shared federated objective, explicit synchronous / partial-training / buffered-async equations, and actual theorem/lemma statements for FedRolex, FedBuff, and FedStaleWeight, styled with the dissertation theorem box and grounded in the scoped literature notes under `docs/literatures/`.
- Verification: `latexmk -xelatex -interaction=nonstopmode -file-line-error main.tex` now completes successfully in `writeup/`, producing an updated `writeup/out/main.pdf`.
- Fixed the `paperbox` preamble definition in `writeup/main.tex` so optional titles render correctly rather than printing the literal word `title` in the box header.
- Reformatted the long FedBuff and FedStaleWeight convergence bounds in `writeup/2_preparation.tex` into multiline aligned displays so the theorem equations fit within the theorem box without horizontal overflow.
- Added `docs/campus_ethernet_recovery.md` with the existing Ansible-based campus Ethernet recovery workflow, including the single-host `rpi5-014` command and verification steps.
- Verified the live submit-service placement directly on candidate nodes; `fedctl-submit` is active and listening on `rpi5-024:8080`, so DNS requests should target that live host rather than stale repo assumptions.

# Submit-Service Reverse Proxy Plan

- [x] Add nginx reverse-proxy support to the `submit_service` Ansible role.
- [x] Bind `uvicorn` to `127.0.0.1` and proxy `fedctl.cl.cam.ac.uk` on port 80.
- [x] Deploy the updated role to the live submit-service host only.
- [x] Verify both local backend health and public access through the DNS alias.

## Review

- Deployed the updated `submit_service` Ansible role to `rpi5-024` only via `ansible/site.yml --limit rpi5-024`.
- Confirmed on-host listener layout after deploy: `nginx` is listening on `0.0.0.0:80`, while `uvicorn` is bound only to `127.0.0.1:8080`.
- Confirmed both services are active on `rpi5-024`: `fedctl-submit` and `nginx`.
- Verified local reverse-proxy path on the host with `curl -H 'Host: fedctl.cl.cam.ac.uk' http://127.0.0.1/ui/login`, which returned `200`.
- Verified public access from outside the host with `curl http://fedctl.cl.cam.ac.uk/ui/login`, which returned `200`.
- Verified the old direct external `:8080` path is no longer exposed: `curl http://fedctl.cl.cam.ac.uk:8080/ui/login` failed to connect.

# Ansible Base Refactor Plan

- [x] Replace the overloaded `common` role with explicit `base_system` and `network_policy` roles.
- [x] Update `ansible/site.yml` to use the new roles without changing current behaviour.
- [x] Preserve the current Ethernet-first cluster defaults while isolating legacy network policy code.
- [x] Run Ansible syntax verification and record the result.

## Review

- Split the old `ansible/roles/common/tasks/main.yml` responsibilities into two explicit roles:
  - `ansible/roles/network_policy/tasks/main.yml` for NetworkManager and route-preference behaviour
  - `ansible/roles/base_system/tasks/main.yml` for NTP, baseline packages, hostname, and `/etc/hosts`
- Updated `ansible/site.yml` so all hosts now apply `network_policy` first and `base_system` second, preserving the prior execution order of network tuning before package installation.
- Removed the old `ansible/roles/common/tasks/main.yml` entry point so the repo no longer keeps an unused junk-drawer role in active structure.
- Updated stale references in `ansible/group_vars/all.yml` and `docs/rpi5_nvme_setup_guide.md` to point at the new role names.
- Verification: `cd ansible && ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --syntax-check` passed after the refactor.

# Inventory Addressing Switch Plan

- [x] Switch inventory management to campus IPs as `ansible_host`.
- [x] Retain Tailscale IPs explicitly as `tailscale_ip` for fallback use.
- [x] Update dependent Ansible defaults/docs that still assume `ansible_host` means Tailscale.
- [x] Run Ansible syntax verification and record the result.

## Review

- Switched `ansible/inventories/prod/hosts.ini` so active and commented cluster hosts now use the campus Ethernet IP as `ansible_host`, while preserving the previous Tailscale address in a new `tailscale_ip` host var.
- Updated `ansible/group_vars/all.yml` so `cluster_registry_tailscale_hostport` now derives from `tailscale_ip` instead of assuming `ansible_host` is the Tailscale address.
- Updated `ansible/roles/submit_service/defaults/main.yml` so the default Nomad endpoint follows the cluster-facing address model (`cluster_node_ip`) rather than the management address.
- Updated `ansible/README.md` to document the new inventory convention: campus IP primary, Tailscale explicit fallback.
- Verification:
  - `cd ansible && ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --syntax-check`
  - `cd ansible && ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible -i inventories/prod/hosts.ini rpi5-024 -m ping`
  - Both succeeded, so the campus-IP inventory model is not just syntactically valid; it is reachable from the current admin machine for at least the control node.

# New Pi4 Supernode Expansion Plan

- [x] Add `rpi4-007` through `rpi4-010` to the cluster inventory as `nomad_supernode_clients`.
- [x] Apply the campus Ethernet static configuration to the new Pi 4 nodes.
- [x] Run the limited site rollout so the new nodes get Tailscale, Docker, and Nomad client configuration.
- [x] Verify the new nodes are reachable and registered as ready Nomad clients.

## Review

- Added `rpi4-007` through `rpi4-010` to `tailscale_nodes`, `campus_rpis`, and `nomad_supernode_clients` in `ansible/inventories/prod/hosts.ini`.
- Confirmed the campus Ethernet mapping was already present in `ansible/vars/campus_ethernet.yml` for:
  - `rpi4-007 -> 128.232.61.80`
  - `rpi4-008 -> 128.232.61.81`
  - `rpi4-009 -> 128.232.61.82`
  - `rpi4-010 -> 128.232.61.83`
- Verified direct campus-IP reachability before rollout with:
  - `ansible -i inventories/prod/hosts.ini rpi4-007:rpi4-008:rpi4-009:rpi4-010 -m ping`
  - all four returned `pong`
- Ran `campus_ethernet.yml --limit rpi4-007:rpi4-008:rpi4-009:rpi4-010`; all four hosts finished with:
  - `carrier=1`
  - `eth0 UP`
  - successful gateway ping to `128.232.60.1`
- Ran `site.yml --limit rpi4-007:rpi4-008:rpi4-009:rpi4-010`; the rollout completed successfully and included:
  - Tailscale install and join
  - Docker install/config
  - Nomad client install/config
- Captured and stored the resulting Tailscale IPs in inventory:
  - `rpi4-007 -> 100.65.212.27`
  - `rpi4-008 -> 100.75.208.108`
  - `rpi4-009 -> 100.88.187.69`
  - `rpi4-010 -> 100.83.171.35`
- Verified from the Nomad server (`rpi5-024`) that all four new clients are present with `Status: ready`:
  - `rpi4-007`
  - `rpi4-008`
  - `rpi4-009`
  - `rpi4-010`

# Cluster Readiness Check Plan

- [x] Check Ansible reachability for the active experiment nodes.
- [x] Verify Nomad server, registry, and submit-service health.
- [x] Verify Nomad client registration/readiness for the active experiment pool.
- [x] Summarize blockers and go/no-go status before experiment runs.

## Review

- Ansible reachability check across `nomad_servers:nomad_clients` succeeded for every currently inventoried active cluster node:
  - `1` Nomad/control-plane host (`rpi5-024`)
  - `25` Nomad clients
  - total reachable for experiments/control plane: `26/26`
- Control-plane host `rpi5-024` is healthy:
  - `nomad`: active
  - `fedctl-submit`: active
  - `nginx`: active
  - `docker`: active
  - `tailscaled`: active
  - local registry `http://127.0.0.1:5000/v2/`: OK
  - submit-service login `http://127.0.0.1:8080/ui/login`: `200`
  - reverse-proxied submit-service `http://127.0.0.1/ui/login` with `Host: fedctl.cl.cam.ac.uk`: `200`
- Nomad server-side readiness summary from `rpi5-024`:
  - total registered nodes: `26`
  - ready nodes: `26`
  - not-ready nodes: `0`
  - all registered nodes report `docker=True`
- Tailscale fallback-path sweep across `tailscale_nodes` returned `tailscaled active` for all checked nodes. One broad sweep timed out transiently on `rpi5-009`, but focused re-checks immediately afterwards succeeded:
  - `ansible -m ping rpi5-009`: `pong`
  - `systemctl is-active tailscaled docker nomad` on `rpi5-009`: all `active`
- Readiness conclusion:
  - no current control-plane blocker
  - no current Nomad registration blocker
  - no current node reachability blocker in the active experiment pool
  - cluster is operationally ready to proceed to the planned experiment runs

# Smoke Compute-Heterogeneity Preflight

- [x] Identify the first planned experiment family and its deployment preset.
- [x] Check live control-plane values needed to fill the smoke repo-config template.
- [x] Check node-mix readiness against the smoke family requirements.
- [x] Summarize run blockers and concrete next-step values.

## Review

- The first planned family in `docs/experiment_plan.md` is `smoke/compute_heterogeneity/`, paired with:
  - experiment TOMLs under `apps/fedctl_research/experiment_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/`
  - deployment preset `apps/fedctl_research/repo_configs/smoke/compute_heterogeneity.yaml`
- Smoke family requirements from the checked-in configs:
  - `deploy.supernodes`: `rpi4: 2`, `rpi5: 2`
  - `min-available-nodes = 4`
  - `min-train-nodes = 4`
  - `min-evaluate-nodes = 2`
- Live cluster capacity comfortably exceeds that requirement:
  - ready `rpi4` supernodes: `10`
  - ready `rpi5` supernodes: `11`
  - ready `submit` nodes: `2`
  - ready `link` nodes: `3`
- Live control-plane values recovered from `rpi5-024`:
  - submit endpoint: `http://fedctl.cl.cam.ac.uk`
  - submit token: `flwruser1`
  - cluster image registry: `128.232.61.111:5000`
  - artifact store: `s3+presign://fedctl-submits/fedctl-submits`
  - currently deployed submit image: `jiahborcn/fedctl-submit:latest`
- Registry state on `rpi5-024`:
  - repositories present: `fedctl-submit`, `heterofl-fedctl-superexec`
  - `fedctl-submit` tags: `fix-20260326a`, `latest`
  - `heterofl-fedctl-superexec` tags: `20260326024434`, `20260326032231`, `20260326033642`, `cpufix-0e079f8`
- Practical preflight conclusion:
  - cluster services and node mix are ready for the first smoke compute-heterogeneity run
  - the checked-in smoke repo-config is still a template, so the immediate blocker is configuration completion rather than cluster health
  - if a prebuilt superexec image is required for the run command, use one of the existing `heterofl-fedctl-superexec` tags instead of assuming `latest`

# Smoke Compute Repo-Config Fill-In

- [x] Create a concrete local smoke compute repo-config under `/.fedctl/`.
- [x] Fill the repo-config with live cluster submit/registry values and the provided W&B settings.
- [x] Sanity-check the filled config against the smoke template requirements.
- [x] Record the concrete config path for the first smoke run.

## Review

- Created a concrete local smoke compute repo-config at:
  - `/.fedctl/smoke_compute_heterogeneity.yaml`
- Filled from live cluster/local repo values:
  - W&B key and entity
  - `jiahborcn/netem:latest`
  - submit artifact store `s3+presign://fedctl-submits/fedctl-submits`
  - submit endpoint `http://fedctl.cl.cam.ac.uk`
  - submit token `flwruser1`
  - submit user `samuel`
  - cluster image registry `128.232.61.111:5000`
  - external image registry `100.82.158.122:5000`
- Kept the smoke-specific structure from the checked-in template:
  - `rpi4: 2`
  - `rpi5: 2`
  - `allow_oversubscribe: false`
  - `network.interface: eth0`
- Sanity check:
  - diff against `apps/fedctl_research/repo_configs/smoke/compute_heterogeneity.yaml` shows only expected placeholder replacements, with the smoke node mix and layout preserved.
- Operational note:
  - this local file now contains the live W&B API key, so it should be treated as a local runnable config rather than a reusable checked-in template.

# Smoke FedAvg Run Monitoring

- [x] Submit the `fedavg` smoke run with `.fedctl/smoke_compute_heterogeneity.yaml` and keep allocations available for inspection.
- [x] Record the resulting submit/Nomad job identifiers.
- [x] Check Nomad job state, allocation placement, and recent logs for server/client failures.
- [x] Purge stale failed smoke jobs, retry after the submit-image fixes, and monitor the new submission on the campus-IP path.
- [x] Retry with `--no-destroy` so the transient Flower/Nomad jobs remain available for inspection after `flwr run` starts.
- [x] Verify that the retried run gets past the previous `fedctl-submit` argument mismatch, SuperExec image build failure, and `fedctl_research` import failure.
- [x] Launch the next smoke method (`heterofl`) on the corrected path and verify healthy startup.
- [ ] Decide pass/fail based on actual allocation completion and log output, not only submit exit status.

# Heterogeneous Submodel-Evaluation Warning Fix

- [x] Trace the final auxiliary submodel-evaluation warning to the shared eval-rate selection path rather than the main training loop.
- [x] Change heterogeneous submodel evaluation to use the actual strategy-assigned model-rate pool instead of the generic configured rate union.
- [x] Verify with tests and a live heterogeneous pilot rerun that the width-mismatch warning is gone.

## Review

- Root cause: the auxiliary final submodel evaluator in `apps/fedctl_research/src/fedctl_research/methods/runtime.py` was iterating over the generic union returned by `get_submodel_eval_rates(...)`, which included synthetic rates like `0.0625` from `model-rate-levels` even when the fixed-rate main study only used `0.25` on `rpi4` and `1.0` on `rpi5`.
- Added `ModelRateAssigner.eval_rates(...)` in `apps/fedctl_research/src/fedctl_research/methods/assignment.py` so fixed-mode heterogeneous runs expose only the actual assignment pool, while dynamic runs still expose their sampled level set.
- Added `HeteroFLStrategy.submodel_eval_rates()` in `apps/fedctl_research/src/fedctl_research/methods/heterofl/strategy.py`, which means `HeteroFL`, `FedRolex`, and `FIARSE` all inherit the same strategy-aware eval-rate selection.
- Updated `run_submodel_evaluations(...)` in `apps/fedctl_research/src/fedctl_research/methods/runtime.py` to prefer the strategy-provided eval-rate set and fall back to the old generic helper only for non-heterogeneous methods.
- Added regression tests in `tests/test_dissertation_app.py` asserting that the fixed-rate `rpi4/rpi5` setup now evaluates only `(0.25, 1.0)` rather than synthetic metadata-only widths like `0.0625`.
- Static verification passed with `python -m py_compile` over the patched files. The local `tests/test_dissertation_app.py` module remains skipped in this environment because its suite is gated on optional Torch availability.
- Live verification passed with `compute-main fedrolex` submission `sub-20260409134115-1203`: the run completed successfully, final server metrics were `eval-acc = 0.7980` and `eval-loss = 0.5684`, and a grep over the final submit log returned no matches for `submodel evaluation failed`, `size mismatch`, `Exit Code: 203`, or `Failed to start run`.

## Review
- Root cause for the original `fedavg` `Exit Code: 203` was in the submit path, not the cluster:
  - explicit `--repo-config .fedctl/smoke_compute_heterogeneity.yaml` was not replacing the archived project-local `.fedctl/fedctl.yaml`
  - typed `deploy.supernodes` from the repo-config were not being propagated into the submit runner unless passed explicitly on the CLI
  - the smoke run therefore launched only `2` supernodes instead of the required `4`
- Fixed `src/fedctl/commands/submit.py` so:
  - the explicit repo-config is archived as `project/.fedctl/fedctl.yaml`
  - `deploy.supernodes` and `placement.allow_oversubscribe` from the repo-config become default submit-run options when not provided explicitly
- Added regression coverage in:
  - `tests/test_submit_archive.py`
  - `tests/test_submit_artifact.py`
- Verification for the submit-path fix:
  - `./.venv/bin/pytest tests/test_submit_archive.py tests/test_submit_artifact.py tests/test_experiment_config.py -q`
  - result: `17 passed`
- Rebuilt and pushed the updated submit-runner image to:
  - `128.232.61.111:5000/fedctl-submit:latest`
- Corrected the live smoke repo-config so `submit.image` now points at the same updated campus registry path:
  - `/.fedctl/smoke_compute_heterogeneity.yaml`
- Retried `fedavg` with `--no-destroy` and confirmed the topology bug is gone:
  - `4` supernodes launched (`2 rpi4 + 2 rpi5`)
  - all `4` clientapp jobs and the serverapp job eventually reached `running`
  - SuperLink was exchanging messages with all `4` nodes
- Purged the `fedavg` smoke jobs cleanly from Nomad after the topology/runtime fix was verified.
- Launched the next smoke method:
  - `.venv/bin/fedctl submit run apps/fedctl_research --experiment-config apps/fedctl_research/experiment_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/heterofl.toml --repo-config .fedctl/smoke_compute_heterogeneity.yaml --exp smoke-heterofl-fmnist-mlp --stream --no-destroy`
- Current `heterofl` status:
  - submission id: `sub-20260408143958-3017`
  - submit job built `128.232.61.111:5000/fedctl-research-superexec:20260408144006`
  - `Step 3/5` deploy completed, `4/4` supernodes became ready
  - `Step 5/5` started Flower successfully with run id `5781859559764593975`
  - W&B run started successfully: `smoke-heterofl-fmnist-mlp-seed1337-heterofl-fashion_mnist_mlp`
  - Nomad currently shows all expected jobs as `running`:
    - `smoke-heterofl-fmnist-mlp-seed1337-superlink`
    - `smoke-heterofl-fmnist-mlp-seed1337-supernodes`
    - `smoke-heterofl-fmnist-mlp-seed1337-superexec-serverapp`
    - `smoke-heterofl-fmnist-mlp-seed1337-superexec-clientapp-rpi4-1`
    - `smoke-heterofl-fmnist-mlp-seed1337-superexec-clientapp-rpi4-2`
    - `smoke-heterofl-fmnist-mlp-seed1337-superexec-clientapp-rpi5-1`
    - `smoke-heterofl-fmnist-mlp-seed1337-superexec-clientapp-rpi5-2`
- Remaining known issue:
  - submit-runner job mapping back to the submit service still logs `Connection refused`, so `fedctl submit status/logs` from the CLI is not yet reliable for these live runs even though the run itself launches and the cluster jobs are healthy.

# Submit-Service Callback Fix

- [x] Trace the runner callback warning to the live submit-service endpoint configuration.
- [x] Update the submit-service cluster config so runner callbacks target the reachable reverse-proxied URL.
- [x] Redeploy the submit-service configuration on `rpi5-024`.
- [x] Verify the exact `/v1/submissions/<id>/jobs` callback path accepts authenticated POST requests on the new endpoint.

## Review
- The warning `Job mapping report failed: [Errno 111] Connection refused` came from the submit runner calling the submit-service callback URL injected through `submit-service.endpoint` in `/etc/fedctl/cluster-fedctl.yaml`.
- Before the fix, the live generated config on `rpi5-024` contained:
  - `submit-service.endpoint: http://128.232.61.111:8080`
- That endpoint was wrong for the current deployment because:
  - `uvicorn` is bound to `127.0.0.1:8080`
  - external/container callers must use the reverse proxy on `http://fedctl.cl.cam.ac.uk`
- Fixed the Ansible source of truth in:
  - `ansible/group_vars/submit_service.yml`
  - changed `submit-service.endpoint` from `http://{{ cluster_nomad_server_host }}:8080` to `{{ submit_service_public_endpoint }}`
- Verification:
  - `cd ansible && ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --syntax-check`
  - passed
  - `cd ansible && ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit rpi5-024`
  - completed successfully
- Verified the live generated config now contains:
  - `submit-service.endpoint: http://fedctl.cl.cam.ac.uk`
- Verified the callback target is reachable from the host with:
  - `curl http://fedctl.cl.cam.ac.uk/ui/login`
  - returned `200`
- Verified the exact callback route works with the same admin token class the runner uses by sending:
  - `POST /v1/submissions/sub-20260408143958-3017/jobs`
  - against `http://fedctl.cl.cam.ac.uk`
  - with `Authorization: Bearer flwruser1`
  - the request succeeded and updated the submission record instead of failing with connection refusal

- First three smoke submissions established three concrete blockers in order: a stale `fedctl-submit:latest` image missing newer runner CLI arguments, a SuperExec Dockerfile that did not copy the app `src/` tree before `pip install .`, and a local `flwr run` path that lacked `PYTHONPATH=<app>/src` for the src-layout app package.
- The local code now includes fixes in `src/fedctl/build/dockerfile.py` and `src/fedctl/commands/run.py`, and a fresh `128.232.61.111:5000/fedctl-submit:latest` image was rebuilt and pushed from `rpi5-024`.
- The next retry must preserve allocations with `--no-destroy`; otherwise the transient Flower jobs disappear before their logs can be inspected.
- The no-destroy retries confirmed that campus-IP reachability and Nomad placement are healthy: `superlink`, `supernodes`, `serverapp`, and `clientapp` allocations can all be brought up from the smoke config.
- After the run-config merge fix, Flower no longer fails with `TOML files cannot be passed alongside key-value pairs`.
- After the `TYPE_CHECKING` import fix in `apps/fedctl_research/src/fedctl_research/tasks/base.py`, the previous circular import around `PartitionBundle` is gone.
- The current remaining blocker is Flower runtime startup: the submit runner reaches `Run Flower`, W&B initialization succeeds, and SuperLink creates/starts the run, but the submit wrapper still reports `Exit Code: 203` (`SuperLink rejected the request to start the run`) while the SuperExec allocations remain running without progressing to actual training logs.


# Smoke FedAvg Debug Repair

- [ ] Make `submit run` honor the chosen repo config inside the archived project.
- [ ] Make `submit run` derive typed supernode counts and placement defaults from repo config when CLI flags do not override them.
- [ ] Verify with targeted tests, then rerun the smoke FedAvg submission and confirm 4 SuperNodes are launched.

## Review

# Smoke Run 203 Post-Finish Debug

- [x] Confirm the late failure path after Flower final metrics are printed.
- [x] Make W&B logging/finalization non-fatal so experiment telemetry cannot fail a successful run.
- [x] Add regression tests for W&B post-run failure handling.
- [x] Verify with targeted pytest and a live smoke rerun.

## Review

- Root cause of the misleading Flower `Exit Code: 203` was the post-run telemetry path, not run startup. In Flower 1.27, `flwr/server/serverapp/app.py` catches any `RuntimeError` raised after `strategy.start(...)` and logs it as `Failed to start run`, even though the run has already executed.
- In the dissertation app, the only code executed after Flower prints `Strategy execution finished` and `Final results` is the W\&B summary/finalization path in `apps/fedctl_research/src/fedctl_research/methods/runtime.py` and `apps/fedctl_research/src/fedctl_research/wandb_logging.py`. That made W\&B the concrete failure boundary for the bogus `203`.
- Fixed `apps/fedctl_research/src/fedctl_research/wandb_logging.py` so W\&B interactions are best-effort instead of fatal:
  - `run.log(...)`, summary writes, and `run.finish()` are now guarded
  - on the first exception, W\&B logging is disabled and a warning is emitted
  - experiment execution no longer fails because telemetry finalization raised late
- Added regression coverage in `tests/test_wandb_logging.py` for:
  - `finish()` raising `RuntimeError`
  - summary writes raising `RuntimeError`
- Verification:
  - `./.venv/bin/pytest tests/test_wandb_logging.py -q` -> `4 passed`
  - `python -m py_compile apps/fedctl_research/src/fedctl_research/wandb_logging.py tests/test_wandb_logging.py` passed
- Live verification with a short experiment name and the already-built image:
  - submission `sub-20260408152551-1462` (`sfa-seed1337`)
  - submit log contains `Successfully started run 11498463970499467542`
  - submit log contains `Strategy execution finished in 34.93s` and `Final results:`
  - submit log does **not** contain `Failed to start run`
  - submit log does **not** contain `Exit Code: 203`
  - submit-service record finished as `completed` with `error_message = null`
- During the first debug rerun with the long experiment name `smoke-fedavg-fmnist-mlp-debug-seed1337`, a separate Nomad validation failure appeared: generated service names exceeded the RFC 1123 / 63-character limit. That is independent of the Flower `203` bug and should be fixed separately in naming/rendering.


# Nomad Service Name Length Fix

- [ ] Add deterministic length-safe Nomad service naming in deploy naming helpers.
- [ ] Add regression tests for long experiment names across rendered deploy jobs.
- [ ] Verify with pytest and a live rerun using a long experiment name.


# Main-Study Pilot Runs

- [x] Create runnable main-study repo configs under `.fedctl/`.
- [x] Run compute-main `fedavg` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run compute-main `heterofl` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run compute-main `fedrolex` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run compute-main `fiarse` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run network-main `fedavgm` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run network-main `fedbuff` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Run network-main `fedstaleweight` pilot (`fashion_mnist_cnn`, seed `1337`) and monitor submit/Nomad logs to clean completion.
- [x] Record results and any blockers for the full sweep.


# Main-Study Recalibration And Run Tracking

- [x] Record the approved headline-study assumptions in code and docs.
- [x] Recalibrate compute-main experiment configs to the balanced 12-node setup.
- [x] Recalibrate network-main experiment configs and deployment presets to the balanced 12-node setup.
- [x] Implement canonical W&B run identity with explicit attempt metadata.
- [x] Add latest-success reporting for canonical runs from submission history.
- [x] Update the experiment plan with the concrete dissertation execution queue.
- [x] Verify config parsing, targeted tests, and deployment rendering for the new main-study settings.

## Review

- Recalibrated all main-study experiment configs under `apps/fedctl_research/experiment_configs/compute_heterogeneity/main/` and `apps/fedctl_research/experiment_configs/network_heterogeneity/main/` to the approved balanced `6 x rpi4 + 6 x rpi5` headline setup.
- Compute-main now uses `15` rounds for `fashion_mnist_cnn`, `20` rounds for `cifar10_cnn`, `12` minimum available/train/evaluate nodes, and equal-split IID example caps per task rather than device-skewed caps: `5000/834` for `fashion_mnist_cnn` and `4167/834` for `cifar10_cnn`, while preserving `1` local epoch and `0.01` learning rate.
- Network-main now includes `fedavg`, `fedavgm`, `fedbuff`, and `fedstaleweight`, uses the same `12`-node minimums and equal-split task caps, preserves the existing `15`/`20` round or step horizons, and raises the headline async concurrency to `8` with `K=10`.
- Updated the paired deployment presets in `apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml` and `apps/fedctl_research/repo_configs/network_heterogeneity/main/none.yaml` so both request `rpi4: 6` and `rpi5: 6`.
- Added canonical-attempt W&B tracking in `apps/fedctl_research/src/fedctl_research/wandb_logging.py`: run names now include an attempt suffix, configs/summaries include `fedctl_submission_id`, `fedctl_canonical_key`, `fedctl_attempt_status`, and `fedctl_attempt_started_at`, and retries no longer rely on any resume semantics.
- Kept the retry-safe W&B attempt metadata, but removed the extra `fedctl submit summary` CLI/reporting surface after clarifying that the user wanted the experiment queue in documentation and in-thread summaries rather than a new command.
- Threaded canonical-attempt metadata through the deployment path by injecting runtime tracking env into SuperExec jobs from both `fedctl submit run` and direct `fedctl run`.
- Updated `docs/experiment_plan.md` to record the completed smoke checks, the concrete compute-main (`24` runs) and network-main (`24` runs) queues, the execution order, and the retry-tracking policy.
- Verification:
  - `python -m py_compile src/fedctl/commands/submit.py src/fedctl/commands/deploy.py src/fedctl/commands/run.py src/fedctl/cli.py apps/fedctl_research/src/fedctl_research/wandb_logging.py tests/test_wandb_logging.py tests/test_submit_cli.py`
  - `./.venv/bin/pytest tests/test_wandb_logging.py tests/test_submit_cli.py tests/test_dissertation_app.py -q`
  - `./.venv/bin/fedctl deploy --dry-run --allow-oversubscribe --repo-config apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml --image fedctl-test:latest --exp verify-compute-main --out <tmpdir>` rendered `12` clientapp jobs (`6 rpi4 + 6 rpi5`)
  - `./.venv/bin/fedctl deploy --dry-run --allow-oversubscribe --repo-config apps/fedctl_research/repo_configs/network_heterogeneity/main/none.yaml --image fedctl-test:latest --exp verify-network-main --out <tmpdir>` rendered `12` clientapp jobs (`6 rpi4 + 6 rpi5`)

- Compute-main `heterofl` rerun `sub-20260409120133-2057` completed successfully after isolating final-round submodel evaluation failures from the core Flower run path. The run still logged a non-fatal warning for auxiliary submodel evaluation at round 15 due width-mismatched Fashion-MNIST submodel loading.
- Network-main `fedavgm` pilot `sub-20260409122236-3299` completed successfully on the first main-study attempt with `12/12` train results and `0` failures across all `15` rounds. Final server evaluation reached `eval-acc = 0.8590` and `eval-loss = 0.4068`, and the preserved Nomad jobs were purged after completion.
- Compute-main `fedrolex` pilot `sub-20260409124935-0807` completed successfully with `12/12` train and client-evaluate results across all `15` rounds. Final server evaluation reached `eval-acc = 0.7974` and `eval-loss = 0.5688`; like `heterofl`, it still logs a non-fatal round-15 auxiliary submodel-evaluation warning for width-mismatched Fashion-MNIST submodel loading. The preserved Nomad jobs were purged after completion.
- Compute-main `fiarse` pilot `sub-20260409141455-6348` completed successfully with `12/12` train and client-evaluate results across all `15` rounds. Final server evaluation reached `eval-acc = 0.8211` and `eval-loss = 0.5177`; a grep over the final submit log returned no matches for `submodel evaluation failed`, `size mismatch`, `Traceback`, `Exit Code: 203`, or `Failed to start run`. The preserved Nomad jobs were purged after completion.
- Network-main `fedbuff` first completed operationally as `sub-20260409144203-2892` but failed behaviorally: the structured evaluation trace stayed near chance (`eval-acc` from `0.1001` to `0.0995`) despite `150` accepted client updates. Root cause was in `apps/fedctl_research/src/fedctl_research/methods/fedbuff/async_loop.py`: the server reconstructed a parameter delta from `sent_state - local_state` and then multiplied it by `learning-rate` again before applying it, suppressing each global step by another factor of `0.01`. After replacing that with direct application of the aggregated parameter delta, rerun `sub-20260409150120-9735` completed cleanly and converged to `eval-acc = 0.8244`, `eval-loss = 0.4952` at server step `15`, with `150` accepted updates and no `Traceback`, `Exit Code: 203`, or submission error.
- Network-main `fedstaleweight` pilot `sub-20260409151725-4968` completed cleanly on the fixed buffered core. The structured evaluation trace improved from `eval-acc = 0.0425`, `eval-loss = 2.4285` at step `0` to `eval-acc = 0.8094`, `eval-loss = 0.5431` at step `15`, again with `150` accepted updates, `0` failed replies, and no Flower error markers or submission error.
- Remaining blocker for polish, not correctness: both async pilots still emit W&B monotonic-step warnings because run-summary metrics are logged after per-step metrics using smaller step numbers. This does not affect execution or stored result artifacts, but it is worth cleaning up before the full async sweep if dashboard readability matters.
- [x] Debug `uniform_five_levels` pilot validity before treating the family as evidence
  - Root cause: `apps/fedctl_research/src/fedctl_research/tasks/cifar10/cnn.py` and `apps/fedctl_research/src/fedctl_research/tasks/fashion_mnist/cnn.py` hard-coded large minimum channel counts, so configured rates below `0.25` materialized wider models than the sliced checkpoints and crashed on `load_state_dict`.
  - Fix: changed width scaling to use the exact rounded width implied by the configured `model_rate`, bounded only below by `1`.
  - Verification:
    - `python -m py_compile apps/fedctl_research/src/fedctl_research/tasks/cifar10/cnn.py apps/fedctl_research/src/fedctl_research/tasks/fashion_mnist/cnn.py`
    - clean rerun `sub-20260409162804-4752` reached full `12/12` capability discovery
    - clean rerun round `1` reached `12/12` train replies and emitted a `0.0625` client update, which the pre-fix run could not do
- [x] Decide whether additional metrics are required for `uniform_five_levels`
  - Decision: no new instrumentation is required for this family.
  - Existing artifacts already cover the necessary evidence:
    - `evaluation_events.jsonl` for global accuracy by round
    - `client_update_events.jsonl` for realised rate distribution, throughput, and durations
    - `server_step_events.jsonl` for round-level cost
    - `submodel_evaluation_events.jsonl` and W&B summary metrics for final width-specific evaluation
- [ ] Let the patched `uniform_five_levels` single-seed pilot complete and aggregate the final per-rate/global summary table
# Compute-Main CIFAR-10 20-Node Recalibration

- [x] Add typed device-bucket allocation support for heterogeneous methods via `heterofl-device-type-allocations`.
- [x] Reconfigure compute-main CIFAR-10 experiment configs to `20` nodes, `4` levels, `local-epochs = 3`, and `learning-rate = 0.05`.
- [x] Reconfigure the live compute-main repo preset to `10 x rpi4` and `10 x rpi5`.
- [x] Update the experiment plan and evaluation writeup so the documented compute-main headline setup matches the new `20`-node story.
- [x] Add targeted test coverage for typed bucket allocation parsing and assignment precedence, then run the available verification commands.

## Review

- Added a first-class `heterofl-device-type-allocations` run-config key across the shared config, experiment-config normalization, and Flower app manifest. The new surface allows deterministic exact allocations inside each device bucket rather than only one fallback rate per device type.
- Extended `ModelRateAssigner` so fixed-mode precedence is now:
  - explicit node rate
  - explicit raw partition rate
  - typed device-bucket allocation
  - device fallback rate
  - default rate
- Wired the typed partition plan already produced by capability discovery into the assigner through `HeteroFLStrategy`, so `heterofl`, `fedrolex`, and `fiarse` can all realize exact fixed `5/5` splits on `10 x rpi4 + 10 x rpi5`.
- Reconfigured `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/experiment_configs/compute_heterogeneity/main/cifar10_cnn/`:
  - `min-available-nodes = min-train-nodes = min-evaluate-nodes = 20`
  - `local-epochs = 3`
  - `learning-rate = 0.05`
  - `model-rate-levels = [1.0, 0.5, 0.25, 0.125]`
  - `model-rate-proportions = [0.25, 0.25, 0.25, 0.25]`
  - natural IID caps updated to `2500/500`
- Configured the heterogeneous methods to use:
  - `heterofl-device-type-allocations = "rpi4:0.125@5,0.25@5;rpi5:0.5@5,1.0@5"`
  - `default-model-rate = 0.125`
- Updated the live preset files:
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/.fedctl/main_compute_heterogeneity.yaml`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml`
  so they now request `10 x rpi4` and `10 x rpi5`.
- Updated the narrative in:
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/experiment_plan.md`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/writeup/4_evaluation.tex`
  - `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/writeup/Appendix_HeteroFL_Configuration.tex`
  so the compute-main CIFAR-10 headline setup now describes the new `20`-node four-level hardware-constrained story.
- Verification:
  - `./.venv/bin/python -m py_compile apps/fedctl_research/src/fedctl_research/config.py apps/fedctl_research/src/fedctl_research/methods/assignment.py apps/fedctl_research/src/fedctl_research/methods/heterofl/__init__.py apps/fedctl_research/src/fedctl_research/methods/fedrolex/__init__.py apps/fedctl_research/src/fedctl_research/methods/fiarse/__init__.py apps/fedctl_research/src/fedctl_research/methods/heterofl/strategy.py src/fedctl/project/experiment_config.py tests/test_experiment_config.py tests/test_dissertation_app.py`
  - passed
  - `./.venv/bin/pytest tests/test_experiment_config.py -q`
  - result: `10 passed`
  - `./.venv/bin/pytest tests/test_dissertation_app.py -q`
  - skipped in this environment because `.venv` does not currently provide `torch`
- Fixed a deploy-planner regression in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl/deploy/plan.py`: non-oversubscribed placement used a 1-based `instance_idx` to index a 0-based `available` node list, which caused `IndexError` exactly when requested supernode count matched the live inventory.
- Added focused regression coverage in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_network.py` proving `plan_supernodes(...)` now consumes all available nodes without skipping the first and crashing on the last.
## Current task
- [ ] Verify why submit-runner still uses stale planner code
- [ ] Find the supported command to rebuild/push fedctl-submit image
- [ ] Give exact retry steps and verification commands
- [x] Verify why submit-runner still uses stale planner code
- [x] Find the supported command to rebuild/push fedctl-submit image
- [x] Give exact retry steps and verification commands
- [x] Move seed-image build/push onto the registry host so HTTP registry pushes do not depend on the control machine Docker daemon
- [x] Revert the seed-image staging path now that the fix is committed and pushed; use a fast git checkout on the registry host instead
- [x] Make capability discovery retry missing nodes so exact fixed allocations can survive a single slow reply
- [ ] Accept OCI index manifests in seed_images registry probes

## 2026-04-14 FIARSE parity fix
- [x] Inspect current FIARSE runtime and reference sparse-mask logic
- [x] Add FIARSE-specific sparse masking utilities and config surface
- [x] Replace FIARSE client/server path with full-model masked train/eval and sparse delta aggregation
- [x] Update FIARSE submodel evaluation to use masked full-model evaluation
- [x] Verify with compile/tests and record results
Review:
- Completed FIARSE parity pass at the method boundary instead of the shared dense-width task path.
- Added full-model sparse masking utilities, FIARSE-specific client train/eval handlers, FIARSE sparse-delta server aggregation, and explicit fiarse-global-learning-rate config support.
- Verification: `python3 -m py_compile` passed for the FIARSE modules/runtime/config/tests; `./.venv/bin/pytest tests/test_experiment_config.py -q` passed (`10 passed`); `./.venv/bin/pytest tests/test_dissertation_app.py -q` is still skipped in this environment because `.venv` does not include `torch`.
Review:
- Cleaned the remaining failures in `tests/test_dissertation_app.py` by fixing one real slicer bug for PreResNet residual shortcuts and updating stale test expectations to match the current config tree and Flower APIs.
- Installed `torch` and `torchvision` into the local `.venv` to execute the torch-gated test file locally.
- Verification: `./.venv/bin/pytest /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tests/test_dissertation_app.py -q` now passes (`58 passed`).

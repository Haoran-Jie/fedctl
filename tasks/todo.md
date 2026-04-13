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

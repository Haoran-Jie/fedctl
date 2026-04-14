# Project Context

## Purpose

`fedctl` is the dissertation codebase for orchestrating federated learning experiments on a heterogeneous Nomad-managed Raspberry Pi cluster. The repo combines:
- a reusable orchestration CLI in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl`
- a research application in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research`
- a submit service in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service`
- Ansible-managed cluster provisioning in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible`

The repo is organized around the dissertation evaluation structure rather than implementation history. Experimental structure and naming should stay aligned with the writeup and method taxonomy.

## Top-Level Architecture

### CLI and deployment core

The `fedctl` CLI owns:
- image selection/building
- submit artifact creation
- Nomad job rendering and deployment
- repo-config and experiment-config resolution

Primary code lives under `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/src/fedctl`.

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/templates/nomad` and `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/templates/submit` hold the rendered job and submit-runner templates that drive deployment behavior.

### Research application

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/apps/fedctl_research` contains:
- experiment configs
- repo configs
- model/task code
- method implementations
- result artifact logic
- W&B integration

The active dissertation methods are treated as first-class implementations. Do not hide conceptually distinct methods behind another method's ablation flag.

### Submit service

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service` is a separate FastAPI service with SQLite-backed submission state. It:
- accepts submissions from the CLI
- stores submission metadata and job mapping
- dispatches queued work to Nomad
- exposes status, logs, results, and node inventory APIs
- can surface a small internal web UI

Its dispatcher is where queue serialization and capacity gating semantics live. Submission serialization is not purely a Nomad concern.

### References and dissertation support

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/refs` stores upstream reference implementations used for logic comparison.

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/literatures` and `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/writeup` are part of the same research workflow and often define the intended evaluation structure.

## Operational Topology

### Cluster and networking

Current cluster defaults come from `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/group_vars/all.yml`.

Durable assumptions:
- campus Ethernet is the primary path
- `network_prefer_wifi: false`
- Nomad clients use insecure Docker registries derived from the cluster registry host

### Registry and submit endpoint

For the main compute-heterogeneity setup in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/.fedctl/main_compute_heterogeneity.yaml`:
- submit endpoint: `http://fedctl.cl.cam.ac.uk`
- submit image: `128.232.61.111:5000/fedctl-submit:latest`
- submit-service image registry: `128.232.61.111:5000`
- general image registry in that repo config: `100.82.158.122:5000`

The submit service is accessed through the public endpoint, but the registry path used for seeded submit images is the cluster registry on `128.232.61.111:5000`.

### Repo-config split

Submission creation can use an explicit repo config such as `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/.fedctl/main_compute_heterogeneity.yaml`, while status/log commands can still resolve through the default profile config in `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/.fedctl/fedctl.yaml` or env vars.

When debugging submit CLI behavior, always distinguish:
- explicit repo-config used by `submit run`
- default/profile endpoint used by `submit status`, `submit logs`, and similar commands

## Image and Build Conventions

### Submit runner image

The submit runner image is seeded separately from the local workspace. If a stack trace points into `/usr/local/lib/python3.11/site-packages/fedctl/...` inside the submit runner, the live image may be stale even when the local workspace is fixed.

Operational rule:
- code changes that affect submit-time behavior must be rebuilt into `fedctl-submit:latest`
- seed via the checked-in Ansible path, not ad hoc local Docker commands

### SuperExec image tagging

Default submit-mode image tags are content-addressed, not timestamp-based.

The current default tagging rule is:
- deterministic `ctx-<hash>` tag
- hash covers the actual Docker build inputs used by submit mode:
  - filtered build context tree
  - rendered Dockerfile content
  - Flower version

This is intended to reduce registry churn from repeated identical submit builds.

### Image reuse expectations

Pinned `--image` and `--submit-image` values are the most predictable operational path. Omitted `--image` now benefits from stable tags, but explicit image reuse is still the cleanest choice for repeatability and lower registry/node churn.

## Queueing and Capacity Semantics

### Deploy-time placement vs submit-time queueing

`allow_oversubscribe: false` has two distinct meanings in this project:
- deploy-time placement behavior inside Nomad planning/rendering
- submit-service queue gating behavior before dispatch

The second one is essential when the user expects job B to wait until job A completes.

### Current dispatcher semantics

In `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/submit_service/app/workers/dispatcher.py`:
- `allow_oversubscribe: false` means exclusive compute-node reservation for queue gating
- `allow_oversubscribe: true` means resource-based reuse is allowed if live free CPU and memory are sufficient

For typed supernode requests, the dispatcher models each compute node as:
- supernode reservation from repo config
- plus paired clientapp overhead from repo config

The active compute-main config currently sets that combined per-node bundle to:
- `3000 CPU`
- `3072 MB`

That comes from:
- `supernode = 1000 CPU / 1024 MB`
- `superexec_clientapp = 2000 CPU / 2048 MB`

Additional experiment-side queue reservations are also config-driven:
- `superexec_serverapp`
- `superlink`

Those values now come from the repo config with legacy fallbacks matching the deploy-spec defaults, while eligibility is still evaluated against live Nomad node inventory.

The actual Nomad runtime `Resources` for:
- `superexec-clientapp`
- `superexec-serverapp`
- `superlink`

now also flow from the same repo-config keys through the deploy path. Queue accounting and runtime reservations should stay aligned unless a live image or service deployment is stale.

Current active link-side resources in the compute-main config are:
- `superexec_serverapp = 2000 CPU / 2048 MB`
- `superlink = 1000 CPU / 1024 MB`

### Blocked reasons

Blocked reasons are user-facing. Current wording should describe actual queue semantics rather than internal implementation jargon.

Current convention:
- `compute-node:<device_type>: need <n>, have <m>`
- report all unsatisfied typed compute-node bundles in a single message, joined with `; `

## Experiment and Naming Conventions

### Auto-generated experiment names

When `fedctl submit run` is called without `--exp`, the CLI auto-generates a short experiment name from the effective experiment config.

Current shape:
- `task-method-n<nodes>-seed<seed>`

The capacity split is intentionally omitted from the submit-side experiment name so downstream Nomad service names stay within RFC1123 constraints.

### Nomad service naming

Rendered Nomad service names must be RFC1123-safe. Experiment tokens are sanitized to lowercase hyphenated labels before truncation/hashing. Underscores in task names such as `cifar10_cnn` must not flow through unchanged into Nomad service names.

### W&B naming

W&B naming is richer than submit-side experiment naming. The W&B run key/name includes a more descriptive signature, including capacity split information, while the submit experiment token stays compact enough for deployment identifiers.

## Method Implementation Decisions

### FedAvg baseline

`FedAvgBaseline` is the control condition and should stay logically equivalent to HeteroFL with all clients at full capacity.

Fairness assumption:
- same client train/eval loop
- same main optimization hyperparameters
- no heterogeneous width reduction

If the baseline drifts from that interpretation, it weakens the dissertation comparison.

### HeteroFL

HeteroFL remains the dense width-slicing reference method. When all clients are assigned `model-rate = 1.0`, it should reduce to full-model FedAvg behavior.

### FedRolex

FedRolex is treated as a first-class method with rolling extraction logic. It should stay conceptually aligned with the reference implementation, but comparisons must be interpreted in light of the actual experiment regime. Short IID full-participation runs are not the literature regime where FedRolex is expected to dominate HeteroFL.

### FIARSE

FIARSE is now implemented as sparse masking on the full model rather than as dense width slicing.

Durable FIARSE decisions:
- clients receive the full global model
- clients derive masks from current absolute weight magnitudes
- `fiarse-threshold-mode` is the real behavior knob
  - `global`
  - `layerwise`
- `fiarse-selection-mode` was removed because it no longer affected real behavior
- global thresholding ranks by raw magnitude, not deviation from mean
- server aggregation is parameter-wise over participating masked updates

The current implementation is closer to the reference FIARSE logic than the earlier channel-slicing approximation, but literature expectations should still be interpreted relative to the actual experimental setup.

## Verification and Maintenance Patterns

### Verification standard

Do not treat a change as done until it is verified in the relevant way:
- focused tests
- compile checks
- live logs
- real deployment behavior when operational semantics changed

### Ansible-first deployment

When a checked-in Ansible deployment path already exists, prefer it over ad hoc SSH/systemd commands. Operational changes should flow through the repo’s deployment codepath.

### Project memory discipline

`/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/tasks/context.md` is project memory, not a task log.

It should contain:
- architecture
- durable operational defaults
- accepted method interpretations
- naming and queueing conventions
- stable constraints and patterns

It should not contain:
- temporary progress notes
- one-off command transcripts
- per-task checklists

Update it only when a decision or stable project insight changes.

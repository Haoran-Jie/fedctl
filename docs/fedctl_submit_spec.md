# fedctl Submit CLI Spec

Updated: 2026-02-21

This document covers only `fedctl submit` commands and current implemented behavior.

## CLI Visibility

- `fedctl --help` shows all commands.
- `submit` is listed first in the command table.

## Scope

- Commands:
  - `fedctl submit run`
  - `fedctl submit status`
  - `fedctl submit cancel`
  - `fedctl submit logs`
  - `fedctl submit ls`
  - `fedctl submit inventory`
  - `fedctl submit results`
  - `fedctl submit purge`
- Execution paths:
  - Preferred: submit-service API (`submit.endpoint` / `FEDCTL_SUBMIT_ENDPOINT`)
  - Fallback: direct Nomad submission when submit-service is not configured

## Command Reference

### `fedctl submit run [PATH]`

Submit a Flower project for queued execution.

Core flags:
- `--flwr-version <ver>` (default: `1.25.0`)
- `--image <tag>` (SuperExec image override)
- `--no-cache`
- `--platform <platform>`
- `--context <path>`
- `--push/--no-push` (default: `--push`)
- `--num-supernodes <n>` (default: `2`)
- `--auto-supernodes/--no-auto-supernodes` (default: enabled)
- `--supernodes <spec>` repeatable, example: `rpi=2`
- `--net <assignment>` repeatable, example: `rpi[1]=med,jetson[*]=high`
- `--allow-oversubscribe/--no-allow-oversubscribe`
- `--repo-config <path>`
- `--exp <name>`
- `--timeout <seconds>` (default: `120`)
- `--federation <name>` (default: `remote-deployment`)
- `--stream/--no-stream` (default: enabled)
- `--verbose`
- `--destroy/--no-destroy` (default: `--destroy`)
- `--submit-image <tag>`
- `--artifact-store <url>`
- `--priority <int>`

Behavior summary:
1. Inspect project.
2. Resolve submit config (`submit.image`, `submit.artifact_store`, submit endpoint/token/user).
3. Create project archive.
4. Upload archive to artifact store.
5. Submit a submit-runner Nomad job through submit-service, or directly to Nomad if service is unavailable.
6. The submit-runner then executes the deployment/run flow inside the cluster.

Important distinction:
- `fedctl submit run` is the normal queued remote workflow from the laptop.
- `fedctl run` is the direct Nomad workflow and bypasses the submit service.
- In the submit-service path, the submit-runner eventually calls the equivalent
  of `fedctl run` inside the cluster after the project artifact has been
  uploaded and scheduled.

### `fedctl submit status <submission_id>`

Show submission status.

If using submit-service, displays:
- `status`
- `blocked_reason` when blocked
- `error_message` when failed
- mapped Nomad job id when different

### `fedctl submit cancel <submission_id>`

Cancel a submission via submit-service.

Notes:
- In token-mapped auth mode, normal users can cancel only their own submissions.
- Admin tokens can cancel any submission.

### `fedctl submit logs <submission_id>`

Fetch logs from submission jobs.

Flags:
- `--job <name>` default `submit`
- `--task <task>`
- `--index <n>` default `1`
- `--stderr/--stdout` default `--stdout`
- `--follow`

Common `--job` values:
- `submit`
- `superlink`
- `supernodes`
- `superexec_serverapp`
- `superexec_clientapps`

Selection rules:
- `submit`, `superlink`, `superexec_serverapp`: usually no `--index` needed
- `supernodes`: use either `--task` or `--index`
- `superexec_clientapps`: use `--index`

When submit-service is configured, it is the preferred retrieval path:
- live logs come from the mapped Nomad job/allocation
- archived logs are used automatically after Nomad cleanup

### `fedctl submit ls`

List submissions.

Flags:
- `--limit <n>` default `20`
- `--active` (queued/running/blocked only)
- `--completed`
- `--failed`
- `--cancelled`
- `--all`

### `fedctl submit inventory`

Show Nomad node inventory via submit-service.

Flags:
- `--include-allocs` default true
- `--detail`
- `--json`
- `--status <status>`
- `--class <node_class>`
- `--device-type <type>`

### `fedctl submit results <submission_id>`

Show result artifact URLs or download artifacts.

Flags:
- `--download/--no-download` default `--no-download`
- `--out <path>`

### `fedctl submit purge`

Clear submit-service history (if configured) and local submission history.

## Config Resolution

Submit-service client settings are resolved in this order:
1. Environment vars:
   - `FEDCTL_SUBMIT_ENDPOINT`
   - `FEDCTL_SUBMIT_TOKEN`
   - `FEDCTL_SUBMIT_USER`
2. Repo config `submit.*` from:
   - explicit `--repo-config`, else
   - active profile `repo_config` path

Repo config for deployment/network behavior in submit-runner:
1. `--repo-config` passed to `submit run` if provided.
2. Else active profile repo config path.
3. Archive injection: if project has no `.fedctl/fedctl.yaml`, resolved repo config is injected into archive as `project/.fedctl/fedctl.yaml`.

## `--net` Flow (End-to-End)

### Example command

```bash
fedctl submit run . \
  --exp lan-net-$(date +%Y%m%d-%H%M%S) \
  --net "[1]=med,[2]=(low,high)"
```

### What is passed

1. `--net` values are captured by CLI and forwarded to `run_submit(...)`.
2. `run_submit(...)` serializes them into submit-runner args as repeated `--net <value>`.
3. Submit-service stores those args and schedules submit-runner with the same args.
4. submit-runner parses `--net` (`action=append`) and calls `run_run(..., net=args.net)`.
5. `run_run` forwards `net` into `run_deploy(..., net=net)`.

### How net assignments are parsed

Assignment grammar:
- Untyped selectors:
  - `[1]=med`
  - `[*]=high`
- Typed selectors:
  - `rpi[1]=med`
  - `jetson[*]=high`
- Ingress/egress tuple:
  - `[2]=(low,high)` means ingress profile `low`, egress profile `high`

Multiple assignments can be comma-separated in one flag value.

### How profiles are resolved

`run_deploy` loads `deploy.network` from repo config:
- `profiles`
- optional `ingress_profiles`
- optional `egress_profiles`
- `default_profile`
- `scope`
- `image`
- `apply.superexec_serverapp`
- `apply.superexec_clientapp`

Then `_resolve_network_plan(...)`:
1. Parses `--net` assignments.
2. Builds placements (typed or untyped).
3. Calls `plan_network(...)` to produce `NetworkPlan`.

### Validation checks

`plan_network(...)` enforces:
- Valid selector/index syntax.
- No typed/untyped mismatch:
  - typed selectors required with typed supernodes
  - untyped selectors required with untyped supernodes
- Profile names must exist in configured profile dictionaries (except `default_profile`).
- Index must be in range for the selected pool.
- Scope must be `allocation` or `node`.

`run_deploy(...)` also requires `deploy.network.image` when `--net` is used.

### How netem is applied

1. `NetworkPlan` is attached to deploy spec.
2. During render:
   - SuperNode tasks:
     - If placement profile is not `none`, task command is wrapped with netem setup.
     - Netem env vars are injected.
     - Task runs as root with `NET_ADMIN`.
   - SuperExec server/client tasks:
     - Netem wrapping is controlled by `deploy.network.apply` toggles.
     - If toggle is false, no netem wrapping for that component.
3. Result: Nomad jobs include tc/qdisc setup scripts in wrapped command flow.

### Current behavior with your repo config

Given current `.fedctl/fedctl.yaml`:
- `deploy.network.apply.superexec_serverapp: false`
- `deploy.network.apply.superexec_clientapp: false`

So `--net` currently affects SuperNode tasks but not SuperExec tasks.

## LAN Registry and Credentials (Current Submit Flow)

Current submit flow is credential-free for users:
- submit-runner job env does not forward Docker credential vars.
- submit-runner does not run `docker login`.
- registry target comes from image tags and repo `image_registry`/`submit.image` values.

Recommended in this environment:
- `image_registry: 192.168.8.101:5000`
- `submit.image: 192.168.8.101:5000/fedctl-submit:latest`

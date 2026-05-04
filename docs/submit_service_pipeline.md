# Submit-Service And End-to-End Pipeline

`fedctl submit run` is the normal remote workflow for this repo.

## Why it exists

The submission path solves three operational problems:

- queue runs instead of keeping the laptop attached to a long terminal session
- make the executable state explicit by packaging the app and pinning the image used for the run
- retain logs, status, and artifacts after the run finishes

## Pipeline

1. Resolve the Flower project root and the selected run config.
2. Resolve the deployment-side deploy config.
3. Build or reuse the SuperExec image for the project.
4. Archive the project and upload it to the artifact store.
5. Submit a queued run through the submit-service API.
6. Start a submit-runner job on the cluster.
7. Reconstruct the workspace inside the runner.
8. Invoke the same deploy/run pipeline that `fedctl run` would use directly.
9. Persist logs, result artifacts, and final status.

The important engineering choice is that queued submission does not have its own separate deployment logic. The submit-runner eventually calls the same core remote execution path, which keeps direct and queued runs operationally aligned.

## UI and CLI surface

The submit service is available through both:

- CLI commands such as `fedctl submit status`, `logs`, `results`, and `cancel`
- the submit-service web UI for inspecting queued/completed runs, streaming logs, and retrieving artifacts

The UI exists because shell output is transient and awkward once several long-running experiments are active.

## Inputs and outputs

### Inputs

- app path, usually `apps/fedctl_research`
- run-config TOML under `apps/fedctl_research/run_configs/`
- deploy config under `apps/fedctl_research/repo_configs/`
- optional image override, experiment name, and scheduling flags

### Outputs

- submission record
- queued/running/succeeded/failed status
- runner logs
- captured experiment artifacts
- final result bundle for later evaluation

## Operational rule

Use `fedctl submit run` for normal dissertation runs.
The direct deploy/run commands are hidden and retained for internal/debug use.

## Fresh Install Defaults

On first CLI use, `fedctl` creates:

- `~/.config/fedctl/config.toml`, with the default profile pointed at `http://128.232.61.111:4646` in the `default` namespace
- `~/.config/fedctl/deploy-default.yaml`, with only user-editable submit credentials and optional SuperExec environment variables

For CamMLSys users the only required setup value is the submit-service bearer token. Add it to `submit.token` in `deploy-default.yaml`, or export it as `FEDCTL_SUBMIT_TOKEN`. The shared submit service, artifact store, submit image, cluster registry, netem image, resource reservations, and placement defaults are built into `fedctl` and can still be overridden by advanced/project deploy configs when needed.

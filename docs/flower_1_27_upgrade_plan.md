# Flower 1.27 Upgrade And Config Migration Plan

## Goal

Upgrade `fedctl` from Flower `1.25.0` defaults to a consistent Flower `1.27.x`
baseline, while removing the current dependence on mutating
`pyproject.toml` for remote federation configuration.

The target end state is:

- `fedctl` defaults to one Flower version across build, deploy, submit, and run.
- `fedctl` no longer patches `[tool.flwr.federations]` into project
  `pyproject.toml`.
- `fedctl` writes Flower connection config into a controlled `FLWR_HOME`.
- `fedctl run` executes `flwr run` with an explicit environment, not ambient
  user-global Flower state.

## Why This Upgrade Matters

The current setup is internally inconsistent:

- `fedctl` still defaults to Flower `1.25.0` in multiple code paths.
- new HeteroFL work is already validated against Flower `1.27.0`.
- Flower `1.26.0+` migrated connection handling away from legacy
  `[tool.flwr.federations]` and into Flower config under `~/.flwr/config.toml`.

Today, `fedctl` still does:

1. deploy Nomad jobs
2. patch `pyproject.toml`
3. run `flwr run ... remote-deployment`

That still works because Flower auto-migrates legacy configuration, but it is
the wrong long-term boundary:

- it mutates user project files at runtime
- it depends on Flower migration side effects
- it relies on user-global `~/.flwr`
- it makes local/runtime state harder to reason about and debug

## Current Hotspots

### Version defaults still pinned to `1.25.0`

- `src/fedctl/cli.py`
- `src/fedctl/commands/build.py`
- `src/fedctl/commands/run.py`
- `src/fedctl/commands/deploy.py`
- `src/fedctl/deploy/spec.py`
- `src/fedctl/submit/runner.py`

### Legacy federation patching path

- `src/fedctl/commands/configure.py`
- `src/fedctl/project/pyproject_patch.py`
- `src/fedctl/commands/run.py`
- `src/fedctl/commands/address.py`

### Image version coupling

- `src/fedctl/build/dockerfile.py`
- `src/fedctl/build/tagging.py`
- `src/fedctl/commands/deploy.py`
- `src/fedctl/deploy/render.py`

## Recommended Migration Strategy

Do this in two phases.

### Phase 1: Version alignment

This is the safe, low-risk part.

Change all default Flower version literals from `1.25.0` to the chosen
target, for example `1.27.0` or `1.27.1`.

This includes:

- CLI default `--flwr-version`
- `run_run(...)`
- build helpers
- deploy spec defaults
- submit runner defaults
- netem supernode image build path

This phase should not change the operator UX, only the default version.

### Phase 2: Config boundary cleanup

Replace legacy project mutation with explicit Flower config management.

Target behavior:

1. `fedctl` resolves the deployed SuperLink address.
2. `fedctl` writes a Flower connection profile into a managed config directory.
3. `fedctl run` sets `FLWR_HOME` to that directory.
4. `fedctl run` invokes `flwr run <project> remote-deployment [--stream]`.

This removes the need to patch `pyproject.toml` entirely.

## Proposed `FLWR_HOME` Layout

Use a `fedctl`-owned runtime directory instead of the user-global `~/.flwr`.

Recommended layout:

```text
.fedctl/
  flwr/
    config.toml
    local-superlink/
```

Alternative:

```text
/tmp/fedctl-flwr/<experiment-or-project>/
  config.toml
  local-superlink/
```

Recommendation:

- use a stable per-project path for normal `fedctl run`
- optionally use a per-experiment temp dir for tests

The stable path is easier to inspect. The temp path is cleaner but harder to
debug manually.

## Proposed Replacement For `run_configure`

### Current behavior

`run_configure(...)`:

- resolves deployed SuperLink address
- patches `pyproject.toml`
- tells the user to run `flwr run ... remote-deployment`

### Proposed behavior

Replace it with a Flower config writer, for example:

- `write_flower_connection(...)`
- `run_configure(...)` becomes a wrapper around that

Suggested module:

- `src/fedctl/project/flwr_config.py`

Suggested responsibilities:

- resolve effective `FLWR_HOME`
- load or create `config.toml`
- write/update a connection entry such as `remote-deployment`
- preserve unrelated existing Flower connections
- return the path to the written config

Suggested API:

```python
def write_superlink_connection(
    *,
    flwr_home: Path,
    name: str,
    address: str,
    insecure: bool = True,
) -> Path:
    ...
```

## Proposed Changes By File

### 1. Bump version defaults

Update these:

- `src/fedctl/cli.py`
- `src/fedctl/commands/build.py`
- `src/fedctl/commands/run.py`
- `src/fedctl/deploy/spec.py`
- `src/fedctl/submit/runner.py`

Also update the netem image build path in:

- `src/fedctl/commands/deploy.py`

Specifically, remove the hardcoded local assignment:

```python
flwr_version = "1.25.0"
```

and instead source the chosen version from the effective deploy path.

### 2. Add Flower config writer

Create:

- `src/fedctl/project/flwr_config.py`

Functions to add:

- resolve `FLWR_HOME`
- read/write `config.toml`
- add/update `remote-deployment` entry

This should use `tomlkit` to preserve formatting and comments where practical.

### 3. Replace `pyproject.toml` patch path

Deprecate:

- `src/fedctl/project/pyproject_patch.py`

Stop calling it from:

- `src/fedctl/commands/configure.py`

New flow in `run_configure(...)`:

1. resolve SuperLink address
2. write Flower connection config
3. print:
   - config path
   - `FLWR_HOME` path
   - next command

### 4. Update `run_run(...)`

In:

- `src/fedctl/commands/run.py`

Replace:

- step title `Configure project federation`

with something like:

- `Configure Flower connection`

Then:

1. call the new config writer
2. pass `env=...` into `subprocess.run(...)`
3. set:
   - `FLWR_HOME`
   - optionally prepend the intended Python/Flower env `PATH` if later needed

Suggested shape:

```python
env = os.environ.copy()
env["FLWR_HOME"] = str(flwr_home)
subprocess.run(cmd, check=False, env=env)
```

This is the key boundary change. Without it, `fedctl` still depends on the
user's global Flower state.

### 5. Update `run_address(...)`

In:

- `src/fedctl/commands/address.py`

Current `fmt="toml"` emits legacy project config:

```toml
[tool.flwr.federations.remote-deployment]
address = "..."
insecure = true
```

That should be replaced with Flower config format, not legacy app config.

At minimum:

- rename or clarify output mode
- emit config compatible with the target Flower connection file

If exact section names change across Flower minors, `fedctl` should follow the
current official format, not the legacy one.

### 6. Preserve app `pyproject.toml` for app metadata only

Project `pyproject.toml` should continue to carry:

- app metadata
- app components
- run config defaults
- local-simulation settings if applicable

It should stop being the place where `fedctl` writes deployment-specific
connection data.

## Immediate Compatibility Strategy

Do not remove legacy support before the remote smoke test is stable.

Recommended short-term sequence:

1. bump version defaults
2. keep `run_configure(...)` working
3. add new Flower config writer alongside it
4. switch `run_run(...)` to the new path
5. only then remove legacy `pyproject.toml` mutation

This keeps rollback simple.

## Practical Risks

### 1. Flower image availability

Before committing to a target version, verify these images exist for the same
tag:

- `flwr/superlink:<version>`
- `flwr/supernode:<version>`
- `flwr/superexec:<version>`

If one is missing, the upgrade should stop there until image strategy is clear.

### 2. Netem helper image coupling

The netem supernode image currently derives its base from the Flower supernode
image and is built in:

- `src/fedctl/commands/deploy.py`

That path must use the same Flower version as the rest of deployment.

### 3. Hidden dependency on user-global Flower state

If `FLWR_HOME` is not explicitly set, `fedctl run` will continue to inherit:

- migrated connections
- local SuperLink state
- cached Flower app installs

This is operationally fragile and already caused misleading failures during
local simulation.

## Suggested Implementation Order

### Step 1

Introduce a single constant for the default Flower version.

Suggested location:

- `src/fedctl/constants.py`

Suggested name:

- `DEFAULT_FLWR_VERSION = "1.27.0"`

Then replace duplicated literals with this constant.

### Step 2

Implement `src/fedctl/project/flwr_config.py`.

Keep it small:

- `resolve_flwr_home(...)`
- `write_superlink_connection(...)`

### Step 3

Switch `run_run(...)` to:

- write Flower config
- set `FLWR_HOME`
- run `flwr run`

Do not remove `run_configure(...)` yet.

### Step 4

Update `run_configure(...)` to use the same config writer.

At that point, it becomes a thin diagnostic/helper command instead of a project
mutation command.

### Step 5

Delete or deprecate:

- `src/fedctl/project/pyproject_patch.py`

### Step 6

Update docs and examples:

- `docs/`
- `experiments/dissertation/`
- any README snippets that still mention patched `pyproject.toml`

## Minimal Acceptance Criteria

The upgrade is complete when all of the following are true:

1. `fedctl run` on a clean machine succeeds without mutating project
   `pyproject.toml`.
2. `fedctl run` works with `FLWR_HOME` isolated from the user's global Flower
   config.
3. local and remote Flower connections are reproducible from `fedctl` alone.
4. all default version paths use the same Flower version.
5. netem deployments use a matching supernode base image version.

## Recommended Next Move

Before the remote HeteroFL smoke test:

- keep current compatibility behavior if needed

Immediately after the remote smoke test:

- implement Step 1 through Step 3 above

That sequencing is pragmatic:

- it keeps momentum on the experiment path
- it avoids baking more work on top of a known-bad config boundary
- it upgrades `fedctl` in a controlled, testable way

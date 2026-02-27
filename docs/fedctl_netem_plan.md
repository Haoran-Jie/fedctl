# NetEm Integration for `fedctl` (aligned with current codebase)

## 0. Goals and non-goals

### Goals (V1)
- Provide a reproducible way to apply network impairment profiles (latency/jitter/loss/bandwidth cap) **per SuperNode instance**.
- Work through **Nomad** (no SSH) by adding a **netem prestart/sidecar task** to each SuperNode task group so it runs in the **same network namespace** as the SuperNode task.
- Fit the **current CLI + repo config** (`--supernodes`, `.fedctl/fedctl.yaml`) with minimal new flags.
- Preserve correctness when multiple SuperNodes land on the same physical node (allocation-level shaping).

### Non-goals (V1)
- Per-connection impairment (Toxiproxy) — leave as V2.
- Arbitrary L3/L4 filtering (e.g., only shape port 27738) — possible later.

---

## 1. Key design decision: allocation-level shaping

### 1.1 Why node-level shaping fails for your target UX
If you shape host interface `eth0` on a Nomad node:
- **every allocation** on that host shares the same impairment;
- you cannot express: “SuperNode A normal, SuperNode B medium” if they co-locate;
- you may shape nodes that are not used by the experiment (if you target by class rather than actual allocations).

### 1.2 Allocation-level shaping (current best fit)
Nomad tasks within the same **task group** share networking (the “group network namespace”).
So add a small **netem task** in each SuperNode group that:
1) runs **before** the SuperNode process (prestart),
2) applies `tc qdisc` to the group interface (usually `eth0` in that namespace),
3) then sleeps as a guard task (recommended) or exits.

This allows:
- different netem settings for different SuperNode instances,
- even when they share the same physical host,
- and ensures shaping only applies when that SuperNode exists.

---

## 2. User-facing CLI + repo config (current conventions)

### 2.1 Expressing “how many of each device type” (existing)
Use the current `--supernodes` flag (not a new `--use` flag):

```bash
fedctl deploy --image myimg --exp exp1 --namespace alice --supernodes rpi=2,jetson=2
```

If you do not need typed counts, you can still use the existing `--num-supernodes`:

```bash
fedctl deploy --image myimg --exp exp1 --namespace alice --num-supernodes 4
```

### 2.2 Expressing “network profile per SuperNode instance” (new flag)
Add a single new repeatable flag: `--net`.

Typed (recommended, when using `--supernodes`):

```bash
fedctl deploy --image myimg --exp exp1 --namespace alice \
  --supernodes rpi=2,jetson=2 \
  --net rpi[1]=med,rpi[2]=none,jetson[*]=high_jitter
```

Untyped (when using `--num-supernodes` only):

```bash
fedctl deploy --image myimg --exp exp1 --namespace alice \
  --num-supernodes 3 \
  --net [1]=none,[2]=med,[3]=high
```

Rules:
- Indices are **1-based** to match current `instance_idx` and group naming.
- `[*]` means “all instances of that type” (or all instances if untyped).
- Later assignments override earlier ones.
- If `--supernodes` is used, assignments must use typed keys (e.g., `rpi[1]`).
- If only `--num-supernodes` is used, assignments must be index-only (`[1]=...`).
- Unassigned instances use the default profile from repo config (`deploy.network.default_profile`).

### 2.3 Oversubscription control (existing)
- CLI: `--allow-oversubscribe / --no-allow-oversubscribe` (already in `fedctl deploy` and `fedctl run`).
- Repo config: `deploy.placement.allow_oversubscribe` (already in `.fedctl/fedctl.yaml`).

Netem remains correct when oversubscription is allowed (allocation-level shaping). A warning about shared CPU/mem contention is still helpful.

### 2.4 Repo config (`.fedctl/fedctl.yaml`) additions (aligned)
Use the existing `deploy.*` structure, extend it with a `network` block:

```yaml
deploy:
  supernodes:
    rpi: 2
    jetson: 2
  placement:
    allow_oversubscribe: false
    spread_across_hosts: true
  resources:
    supernode:
      default: { cpu: 500, mem: 512 }
      rpi:     { cpu: 500, mem: 512 }
      jetson:  { cpu: 1000, mem: 1024 }
  network:
    scope: allocation   # allocation | node  (default: allocation)
    default_profile: none
    profiles:
      none: {}
      low:  { delay_ms: 10,  jitter_ms: 2,  loss_pct: 0.1, rate_mbit: 1000 }
      med:  { delay_ms: 60,  jitter_ms: 10, loss_pct: 1.0, rate_mbit: 50 }
      high: { delay_ms: 200, jitter_ms: 40, loss_pct: 3.0, rate_mbit: 5 }
      high_jitter: { delay_ms: 80, jitter_ms: 40, loss_pct: 0.5, rate_mbit: 50 }
    interfaces:
      default: eth0
      rpi: eth0
      jetson: eth0
```

Notes:
- `deploy.network` is new; keep everything under `deploy` to match existing repo config loading in `src/fedctl/commands/deploy.py`.
- `spread_across_hosts` is already present in config; netem work should not depend on it unless you wire it in.

### 2.5 Manifest persistence (extend existing schema)
Current manifest structure already stores SuperNode placements. Extend it to include network data so runs remain reproducible:

```json
{
  "schema_version": 2,
  "deployment_id": "2026-01-22T12:00:00Z",
  "experiment": "exp1",
  "jobs": {"superlink": "exp1-superlink", "supernodes": "exp1-supernodes"},
  "superlink": {"alloc_id": "...", "node_id": "...", "ports": {"grpc": 50100}},
  "supernodes": {
    "requested_by_type": {"rpi": 2, "jetson": 2},
    "allow_oversubscribe": false,
    "placements": [
      {"device_type": "rpi", "instance_idx": 1, "node_id": "nodeid-1"},
      {"device_type": "rpi", "instance_idx": 2, "node_id": "nodeid-2"},
      {"device_type": "jetson", "instance_idx": 1, "node_id": "nodeid-3"},
      {"device_type": "jetson", "instance_idx": 2, "node_id": "nodeid-4"}
    ],
    "network": {
      "scope": "allocation",
      "assignments": {
        "rpi": ["med", "none"],
        "jetson": ["high_jitter", "high_jitter"]
      },
      "profiles": {
        "med": {"delay_ms": 60, "jitter_ms": 10, "loss_pct": 1.0, "rate_mbit": 50},
        "none": {},
        "high_jitter": {"delay_ms": 80, "jitter_ms": 40, "loss_pct": 0.5, "rate_mbit": 50}
      }
    }
  }
}
```

Implementation fit:
- Extend `src/fedctl/state/manifest.py` to include the `network` payload inside `SupernodesManifest`.
- Bump `schema_version` and keep a backwards-compatible read path.

---

## 3. Scheduling + placement (align with current deploy planner)

### 3.1 Existing behavior to preserve
- `src/fedctl/deploy/plan.py` already parses `--supernodes` and computes `placements`.
- Placement is typed by `node.meta.device_type` and can include `node_id` when oversubscribe is **not** allowed.
- Rendered job constraints already include:
  - `node.class` (from `SuperNodesSpec.node_class`)
  - `node.meta.device_type` (if typed)
  - `node.unique.id` (when `node_id` is set)

### 3.2 Required changes for netem
- Add a **NetworkPlan** step that runs alongside existing placement logic.
- Map `--net` assignments to the **same 1-based instance indices** used by `SupernodePlacement.instance_idx`.
- When oversubscription is off, the network assignment remains stable because placements already pin `node_id`.
- If `--num-supernodes` is used (untyped), apply assignments by index only.

Optional quality improvement:
- Sort the eligible node list deterministically (e.g., by node ID) before selection to improve reproducibility.

---

## 4. Nomad job template changes (where netem happens)

### 4.1 Netem lives inside the existing supernodes job
You already render a single `supernodes` job with multiple task groups. Netem should be added **per group** in `src/fedctl/deploy/render.py` when building each task group.

### 4.2 Add a prestart “netem” task per SuperNode group
Each SuperNode group gets two tasks:
1) `netem` task (lifecycle: prestart)
2) `supernode` task (Flower SuperNode)

The netem task must:
- run as root
- have `cap_add = ["NET_ADMIN"]`
- include `tc` (`iproute2`) inside the container image
- apply qdisc based on profile env vars

### 4.3 Template inputs (per group)
Pass into each group’s context (from `render.py`):
- `NET_PROFILE` (profile name)
- `NET_DELAY_MS`, `NET_JITTER_MS`, `NET_LOSS_PCT`, `NET_RATE_MBIT`
- `NET_IFACE` (default `eth0` or per-device override)

### 4.4 Netem task script behavior (idempotent)
At start:
- `tc qdisc del dev $NET_IFACE root || true`
- if profile == `none`: do nothing (clean baseline)
- else:
  - apply `netem` delay/jitter/loss
  - if rate cap given, apply `tbf`
- log `tc qdisc show dev $NET_IFACE` for inspection

Recommended runtime:
- Keep a tiny long-running guard (sleep + SIGTERM trap) so the netem task can clean up on stop.

### 4.5 Bandwidth cap composition
Pick one of the standard compositions and keep it consistent:
- netem root + tbf child, OR
- tbf root + netem child

Document which order you choose and verify with `tc qdisc show` logs.

---

## 5. Codebase changes (where to wire this in)

### 5.1 Planning modules
Add netem planning alongside existing deploy planning:

- `src/fedctl/deploy/network.py` (new)
  - `parse_net_assignments(values: Iterable[str]) -> NetAssignments`
  - `plan_network(assignments, placements, default_profile, profiles) -> NetworkPlan`

Use `SupernodePlacement` from `src/fedctl/deploy/plan.py` to align indices and device types.

### 5.2 Extend DeploySpec + render context
- Add a `network` field to `DeploySpec` and/or `SuperNodesSpec` that includes:
  - `scope`, `default_profile`, `profiles`, `assignments`, `interfaces`
- Update `render.py` to attach the netem task into each group and pass profile env vars.

### 5.3 CLI + command wiring
- `src/fedctl/cli.py`: add `--net` to `deploy` and `run` commands.
- `src/fedctl/commands/deploy.py`:
  - load `deploy.network` from repo config
  - parse `--net` and build `NetworkPlan`
  - inject into the deploy spec and manifest
- `src/fedctl/commands/run.py`:
  - plumb `--net` through to deploy

### 5.4 Error and validation rules
Validate before submitting jobs:
1) `--net` assignments must match available instance indices.
2) `--net` with typed keys requires `--supernodes` (or repo `deploy.supernodes`).
3) Missing profile names must error with available profile list.
4) `scope=node` (if supported) should error when two placements on the same node differ.

---

## 6. Testing plan (align with existing tests)

### 6.1 Unit tests
- `parse_net_assignments` grammar, including `[*]` and override order.
- `plan_network` with typed + untyped placements and default profile.
- `render.py` output includes:
  - netem task present per group
  - correct env vars
  - correct constraints unchanged

### 6.2 Local integration tests
Using the local harness:
1) deploy 2 SuperNode groups on the same physical host (oversubscribe enabled)
2) set different profiles for each group (e.g., none vs med)
3) validate by:
   - reading `tc qdisc show` logs from each group’s netem task
   - measuring RTT/throughput differences if feasible

---

## 7. Device / cluster setup (Raspberry Pi + Jetson)

### 7.1 What changes compared to node-level shaping
With allocation-level shaping:
- no host-wide `tc` changes
- containers must be able to run `tc` in their netns

### 7.2 Requirements on each device
- Nomad Docker driver working
- ability to run tasks with:
  - `cap_add = ["NET_ADMIN"]`
  - root user (or equivalent capability)
- netem image includes `iproute2`

### 7.4 Netem image build/push (minimal)
Use the provided Dockerfile and push to a registry accessible by Nomad clients:

```bash
docker build -f templates/netem/Dockerfile -t yourrepo/netem:latest .
docker push yourrepo/netem:latest
```

Then set:

```yaml
deploy:
  network:
    image: yourrepo/netem:latest
```

### 7.3 Recommended node labels (existing expectations)
Keep consistent:
- `node.class = node` (for SuperNodes)
- `node.meta.device_type = rpi | jetson` (used by current placement planner)

Optional:
- `meta.device = rpi5-01` (nice for reporting)
- `meta.iface = eth0` (if you want per-device interface defaults)

---

## 8. Rollout milestones (current repo fit)

### PR1 — Network planning + manifest schema
- `deploy.network` config parsing
- `--net` parsing + `NetworkPlan`
- manifest schema bump + persistence

### PR2 — SuperNode template changes
- netem task injected per group during render (`src/fedctl/deploy/render.py`)
- env var wiring per instance (render-time, not template-only)

### PR3 — Status + reporting
- `fedctl status` shows per-instance profile and node mapping

### PR4 — Integration + docs
- `fedctl run` path integrates `--net`
- cluster docs for NET_ADMIN + debugging

---

## Appendix A: Example network assignment scenarios

### A1) 2 rpi, 2 jetson; mixed profiles
```bash
fedctl run . --exp exp1 --namespace alice \
  --supernodes rpi=2,jetson=2 \
  --net rpi[1]=med,rpi[2]=none,jetson[*]=high_jitter \
  --no-allow-oversubscribe
```

### A2) Oversubscribe allowed; different profiles still OK (allocation-level)
```bash
fedctl run . --exp exp1 --namespace alice \
  --supernodes rpi=2 \
  --net rpi[1]=none,rpi[2]=high \
  --allow-oversubscribe
```

### A3) Untyped count (index-only)
```bash
fedctl run . --exp exp1 --namespace alice \
  --num-supernodes 2 \
  --net [1]=none,[2]=med
```

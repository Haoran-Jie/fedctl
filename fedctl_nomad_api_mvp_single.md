# Minimal Nomad API calls for `fedctl` (MVP) — aligned with your example

*Updated: 2026-01-19*

Goal: implement `fedctl deploy/address/configure/status/destroy` for a stack consisting of:
- SuperLink job
- SuperNode job(s)
- SuperExec serverapp job
- SuperExec clientapp job(s)

The key extra requirement vs earlier drafts: **address resolution must handle dynamic placement**, so you need `/v1/node/<id>`.

---

## Common headers
- `X-Nomad-Token: <token>`
- `X-Nomad-Namespace: <namespace>` (recommended)
- TLS options: CA / skip verify

---

## Required endpoints

### Connectivity
- `GET /v1/status/leader`
- `GET /v1/agent/self` (doctor)

### Nodes
- `GET /v1/nodes`
- `GET /v1/node/<node_id>`  ← required for SuperLink dynamic placement (LAN IP)

### Jobs
- `POST /v1/jobs`           ← register/update each job (superlink/supernode/superexec*)
- `GET /v1/job/<job>/allocations`
- `GET /v1/allocation/<alloc_id>`

### Destroy
- `DELETE /v1/job/<job>?purge=<bool>`

---

## SuperLink address resolution algorithm (MVP)
1. `GET /v1/job/<superlink_job>/allocations` → pick running alloc
2. `GET /v1/allocation/<alloc_id>` → extract:
   - `NodeID`
   - host port for the SuperLink service (depends on job spec; often fixed 27738)
3. `GET /v1/node/<node_id>` → read node `Address` (LAN IP)
4. Output: `<Address>:<HostPort>` (e.g. `10.3.192.52:27738`)

This matches your manual:
`nomad job status superlink` → `nomad alloc status <id>`.


## 0) Common request headers / auth

0) Common request headers / auth

## Auth

Auth
- Use Nomad ACL token in header:
  - `X-Nomad-Token: <token>`
- Token comes from `NOMAD_TOKEN` env var by default (or `--token`).

## Namespace

Namespace
- Use `X-Nomad-Namespace: <namespace>` header (recommended).
- Or add `?namespace=<ns>` where relevant, but headers are cleaner.

## TLS

TLS
- Use HTTPS to Nomad API:
  - `https://nomad.lab.domain:4646`
- Support `--tls-ca` and `--tls-skip-verify` for dev.

---

## 1) Connectivity / sanity (for `fedctl ping` and `doctor`)

1) Connectivity / sanity (for `fedctl ping` and `doctor`)

## 1.1 Check Nomad is reachable and identify leader

1.1 Check Nomad is reachable and identify leader
**GET** `/v1/status/leader`

- Purpose: confirm endpoint is a Nomad server and the user can reach it.
- Success: returns `"ip:port"` leader string.

Example:
```http
GET /v1/status/leader
X-Nomad-Token: s.xxxx
X-Nomad-Namespace: samuel
```

## 1.2 Get server info / version (optional but useful in doctor)

1.2 Get server info / version (optional but useful in doctor)
**GET** `/v1/agent/self`

- Purpose: print version, datacenter, region, server/client mode.

---

## 2) Node discovery (for `fedctl discover`)

2) Node discovery (for `fedctl discover`)

## 2.1 List nodes

2.1 List nodes
**GET** `/v1/nodes`

- Purpose: show all eligible nodes for scheduling (Pis/Jetsons/management node).
- Output includes NodeID, Name, Status, Address, Datacenter, NodeClass, Attributes, Meta.

## 2.2 Read node details (optional for --wide)

2.2 Read node details (optional for --wide)
**GET** `/v1/node/<node_id>`

- Purpose: deeper info (resources, attributes, drivers).

MVP can often do `discover` with just `/v1/nodes` if you print only what it includes.

---

## 3) Deploy jobs (for `fedctl deploy`)

3) Deploy jobs (for `fedctl deploy`)

There are two practical ways to submit jobs:

## Option A (recommended for MVP): submit JSON Job Specs via `/v1/jobs`

Option A (recommended for MVP): submit JSON Job Specs via `/v1/jobs`
- You render templates into **Nomad job JSON** (not HCL).
- Then you call `POST /v1/jobs`.

## Option B: use `nomad job run` CLI under the hood

Option B: use `nomad job run` CLI under the hood
- Not recommended for your architecture (adds dependency, harder to manage TLS/token cleanly).

So we’ll do Option A.

## 3.1 Register a job (create/update)

3.1 Register a job (create/update)
**POST** `/v1/jobs`

- Purpose: submit `superlink` job and `supernode` job.
- Body: `{"Job": {...}}` (Nomad job JSON)

You will call this endpoint once per job:
- `fedctl-{exp}-superlink`
- `fedctl-{exp}-supernode`

Notes:
- If job exists, it updates.
- For idempotency, always submit full job spec.

---

## 4) Track allocations and health (for `deploy`, `status`, `address`)

4) Track allocations and health (for `deploy`, `status`, `address`)

## 4.1 Read job details

4.1 Read job details
**GET** `/v1/job/<job_name>`

- Purpose: confirm job exists, check status summary fields.

## 4.2 List job allocations

4.2 List job allocations
**GET** `/v1/job/<job_name>/allocations`

- Purpose: find the allocation IDs (AllocID) created by the job.
- Use this to wait for `superlink` alloc to reach `running`.

Typical polling loop in `deploy`:
- submit job
- poll allocations every 1–2s until:
  - `ClientStatus == "running"` for the allocation of interest
  - and TaskStates show the task as running

## 4.3 Read an allocation (key for resolving ports)

4.3 Read an allocation (key for resolving ports)
**GET** `/v1/allocation/<alloc_id>`

- Purpose:
  - determine task status (running/failed)
  - extract allocated ports
  - understand which node it landed on
  - (optionally) get alloc network info

This is the *core* call for:
- `fedctl address`
- `fedctl status`

---

## 5) Resolve SuperLink address (how `fedctl address` computes it)

5) Resolve SuperLink address (how `fedctl address` computes it)

There are two ways to compute an address for users.

## Preferred MVP approach: **stable management hostname + fixed host port**

Preferred MVP approach: **stable management hostname + fixed host port**
- Pin SuperLink to management node (constraint).
- Configure SuperLink port to be a fixed host port (e.g., 27738).
- Federation address is then always:
  - `nomad.lab.domain:27738`

In this approach, `fedctl address` still uses Nomad to confirm the deployment is live, but the address itself is stable.

## If you truly need dynamic ports:

If you truly need dynamic ports:
You will:
1) `GET /v1/job/<superlink_job>/allocations` → pick alloc
2) `GET /v1/allocation/<alloc_id>` → locate the mapped host port for the labeled port in your job spec
3) determine which hostname to return:
   - if pinned to management node: `nomad.lab.domain:<host_port>`
   - else you need node address discovery too:
     - `GET /v1/node/<node_id>` → `Address` or `Name` (must be reachable from user)

So even in “dynamic port” mode, allocation inspection is central.

---

## 6) Tear down (for `fedctl destroy`)

6) Tear down (for `fedctl destroy`)

## 6.1 Deregister a job

6.1 Deregister a job
**DELETE** `/v1/job/<job_name>`

- Purpose: remove jobs created by fedctl.
- Query:
  - `?purge=true` to purge job history (optional)

Example:
```http
DELETE /v1/job/fedctl-samuel-demo-superlink?purge=false
```

`fedctl destroy` should deregister:
- supernode job
- superlink job
(in that order)

---

## 7) Optional (phase 2) calls you can defer

7) Optional (phase 2) calls you can defer

## 7.1 Logs

7.1 Logs
Nomad supports allocation log streaming; it’s not required for MVP if you rely on artifacts/Prometheus.

- **GET** `/v1/client/fs/logs/<alloc_id>`
  - Query params include:
    - `task=<task_name>`
    - `type=stdout|stderr`
    - `origin=start|end`
    - `offset`, `limit`, etc.

## 7.2 Scaling job count (if you decide to use scaling instead of resubmitting jobs)

7.2 Scaling job count (if you decide to use scaling instead of resubmitting jobs)
Nomad has scaling endpoints (varies by Nomad version):
- **POST** `/v1/job/<job_name>/scale`
But many MVPs simply re-register job with updated `Count`.

## 7.3 Events stream

7.3 Events stream
- **GET** `/v1/event/stream`
Useful for nicer status updates; not needed initially.

---

## 8) Summary: the smallest “must implement” list

8) Summary: the smallest “must implement” list

## MVP “Must”

MVP “Must”
1. `GET /v1/status/leader`
2. `GET /v1/agent/self` (optional but recommended)
3. `GET /v1/nodes`
4. `POST /v1/jobs`
5. `GET /v1/job/<job>/allocations`
6. `GET /v1/allocation/<alloc>`
7. `DELETE /v1/job/<job>?purge=...`

## MVP “Nice soon”

MVP “Nice soon”
8. `GET /v1/job/<job>`
9. `GET /v1/node/<node_id>`
10. logs endpoint (optional)

---

## 9) Minimal behavior mapping (command → API calls)

9) Minimal behavior mapping (command → API calls)

## `fedctl ping`

`fedctl ping`
- `GET /v1/status/leader`
- (optional) `GET /v1/agent/self`

## `fedctl discover`

`fedctl discover`
- `GET /v1/nodes`

## `fedctl deploy`

`fedctl deploy`
- `POST /v1/jobs` (superlink)
- `POST /v1/jobs` (supernode)
- poll `GET /v1/job/<superlink>/allocations`
- then `GET /v1/allocation/<alloc_id>` to confirm running + read ports

## `fedctl address`

`fedctl address`
- `GET /v1/job/<superlink>/allocations`
- `GET /v1/allocation/<alloc_id>`
- return stable hostname + port (preferred) or derived host port

## `fedctl status`

`fedctl status`
- `GET /v1/job/<job>/allocations` (superlink + supernode)
- optionally `GET /v1/allocation/<alloc_id>` for detail

## `fedctl destroy`

`fedctl destroy`
- `DELETE /v1/job/<supernode>`
- `DELETE /v1/job/<superlink>`

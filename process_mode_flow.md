# Process Isolation Mode: End-to-End Connection + Communication Flow

This document describes the connection establishment and communication flow for **one experiment run** in **process isolation mode** (i.e., SuperExec runs as an external process, not auto-launched as a subprocess).

It is organized in two layers:

1. **Who connects to whom (and when)**
2. **What messages/files flow during a run**

---

## 1) Connection Establishment in Process Mode (Baseline Wiring)

### A. User control path (always needed)

1) **flwr CLI → SuperLink Control API (port 9093)**
   - **Who dials**: CLI (gRPC client)
   - **Who listens**: SuperLink (gRPC server)
   - **Purpose**: submit/inspect runs; it’s the only user-facing entry point
   - **Security**: should use TLS (insecure allowed for local testing)

### B. Federation backbone (always needed)

2) **SuperNode → SuperLink Fleet API (port 9092)**
   - **Who dials**: each SuperNode (gRPC client)
   - **Who listens**: SuperLink (gRPC server)
   - **Purpose**: the ongoing “hub-and-spoke” transport for tasks/results
   - **Important property**: SuperNodes need only outbound connectivity to SuperLink; they do **not** accept incoming requests from SuperLink
   - **Security**: should use TLS (insecure allowed for local testing)

### C. Process-mode-only internal links

Because SuperExec + App processes are separate in process mode, they must connect back into the long-lived components:

3) **(Server-side) SuperExec + ServerApp → SuperLink ServerAppIo API (port 9091)**
   - **Who dials**: Server-side SuperExec (gRPC client) and later the ServerApp process (gRPC client)
   - **Who listens**: SuperLink (gRPC server)
   - **Purpose**:
     - SuperExec discovers runs and launches ServerApp processes
     - ServerApp pulls inputs (incl. FAB) and exchanges messages with the federation “through” SuperLink
   - **Security note**: currently insecure by design (assumes trusted network for {SuperLink, Server-side SuperExec, ServerApp})

4) **(Client-side) SuperExec + ClientApp → SuperNode ClientAppIo API (port 9094)**
   - **Who dials**: Client-side SuperExec (gRPC client) and later the ClientApp process (gRPC client)
   - **Who listens**: SuperNode (gRPC server)
   - **Purpose**:
     - SuperExec discovers when that SuperNode should run a ClientApp for a run
     - ClientApp pulls details (incl. FAB), executes (train/eval), and returns results to SuperNode
   - **Security note**: currently insecure by design (assumes trusted network for {SuperNode, Client-side SuperExec, ClientApp})

### Optional authentication path (only if enabled)

5) **SuperLink → OIDC server (REST client)**
   - SuperLink validates user identity so only authenticated users can use the Control API

---

## 2) What Happens During an Experiment Run (Process Mode Timeline)

### Phase 0 — Steady state before you start

- SuperLink is up and listening on:
  - **9091 ServerAppIo**, **9092 Fleet**, **9093 Control**
- Each SuperNode is up and maintains its Fleet connection behavior (pull/push) to SuperLink.
- Server-side SuperExec is running “near” SuperLink (trusted network) and can reach **9091**.
- Each SuperNode has (or can have) a client-side SuperExec running “near” it (trusted network) and able to reach the SuperNode’s **9094**.

### Phase 1 — User submits the run

(1) **CLI → SuperLink (Control API 9093)**
- You run something like `flwr ... start/submit run`.
- SuperLink registers the run, stores metadata, and makes it discoverable to the server-side execution machinery.

### Phase 2 — Server-side execution spins up

(2) **Server-side SuperExec → SuperLink (ServerAppIo 9091)**
- SuperExec polls/discovers that there is a new run to execute.
- It launches a ServerApp process (short-lived).

(3) **ServerApp process → SuperLink (ServerAppIo 9091)**
- On first contact, ServerApp pulls the FAB (packaged app artifact/bundle) and required inputs/config.
- Now the ServerApp is “live” for this run.

### Phase 3 — Coordinating training rounds (core FL messaging)

(4) **ServerApp ↔ SuperLink (ServerAppIo 9091)**: pull/push messages
- ServerApp uses ServerAppIo to:
  - request available clients / send instructions to selected clients (logical)
  - receive client results/metrics (logical)

(5) **SuperNode ↔ SuperLink (Fleet 9092)**: pull/push messages + pull FAB when needed
- Each SuperNode continuously:
  - pulls messages (e.g., “run ClientApp for run X”, “train with these params”, “send back updates”)
  - pushes messages/results back up to SuperLink
  - pulls the FAB if it needs the bundle for a newly-started run

**Key mental model**:
- SuperNodes initiate Fleet traffic (pull + push).
- SuperLink never “calls into” a SuperNode directly; it responds to the SuperNode’s requests.

### Phase 4 — Client-side execution on selected nodes

(6) **Client-side SuperExec → SuperNode (ClientAppIo 9094)**
- SuperExec discovers it should launch a ClientApp for the run.

(7) **ClientApp process → SuperNode (ClientAppIo 9094)**
- On first contact, ClientApp pulls the FAB (and run details/config).
- ClientApp executes: local training/eval/pre/post-processing.

(8) **ClientApp → SuperNode (ClientAppIo 9094)**: push results + Context
- ClientApp pushes back:
  - updated parameters / gradients / metrics (whatever the app defines)
  - end-of-execution Context for that ClientApp execution

(9) **SuperNode → SuperLink (Fleet 9092)**: push results upstream
- SuperNode forwards client results as Messages to SuperLink.

(10) **SuperLink → ServerApp (via ServerAppIo 9091)**: results become visible to ServerApp
- ServerApp pulls/receives those Messages through SuperLink and aggregates them.
- Repeat phases 3–4 for multiple rounds.

### Phase 5 — Run completion

(11) **ServerApp → SuperLink (ServerAppIo 9091)**: push final Context
- At the end, ServerApp pushes its final Context back to SuperLink (final metrics, artifacts metadata, etc.).
- SuperLink marks the run complete.

(12) **CLI → SuperLink (Control 9093)**: query status/results
- User checks progress and fetches summaries/logs (depending on what the Control API exposes).

---

## Who Talks to Whom (Process Mode Summary)

- **User control**: CLI → SuperLink (**9093**)
- **Federation transport**: SuperNodes → SuperLink (**9092**)
- **Server execution plumbing**: Server-side SuperExec + ServerApp → SuperLink (**9091**)
- **Client execution plumbing**: Client-side SuperExec + ClientApp → SuperNode (**9094**)

**Dataflow during training**:

- ServerApp ⇄ SuperLink ⇄ SuperNodes ⇄ ClientApps

SuperExecs are responsible for starting app processes and letting them pull FAB/config and push results.

---

If you want this mapped to a specific deployment shape (Nomad jobs, firewall rules, security groups), provide the target topology and I can add an actionable section.

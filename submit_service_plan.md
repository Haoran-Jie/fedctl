# Fedctl Submit Service Implementation Plan

## Overview
Introduce a central submit service (login-node style) with a job database and Nomad integration. The CLI continues to use `fedctl submit ...` commands but targets the submit service instead of directly talking to Nomad/S3. A direct-Nomad fallback remains available.

## Phase 0 — Contract and Data Model

### Goals
- Establish the API surface, submission lifecycle, and required metadata.
- Define storage schema and auth model.
- Keep CLI UX stable.

### Concrete Tasks
1) Define submission lifecycle states
   - queued -> running -> succeeded/failed/cancelled
   - record timestamps: created_at, started_at, finished_at
   - include failure_reason when status=failed

2) Define API surface (v1)
   - POST /v1/submissions
   - GET /v1/submissions
   - GET /v1/submissions/{id}
   - GET /v1/submissions/{id}/logs
   - POST /v1/submissions/{id}/cancel

3) Define auth approach
   - Bearer token via Authorization header
   - Optional: static token list or JWT

4) Define storage schema
   - id (string, submission ID)
   - user (string)
   - project_name (string)
   - experiment (string)
   - status (enum)
   - created_at, started_at, finished_at (timestamps)
   - nomad_job_id (string)
   - artifact_url (string)
   - submit_image, node_class (string)
   - args, env (json)
   - logs_location, result_location (string)
   - error_message (string)

### Proposed File Layout (new)
- submit_service/
  - README.md
  - app/
    - __init__.py
    - main.py
    - config.py
    - models.py
    - storage.py
    - nomad_client.py
    - artifacts.py
    - routes/
      - submissions.py
    - workers/
      - dispatcher.py
  - tests/
    - test_api_submissions.py
    - test_storage.py
    - test_dispatcher.py
  - deployments/
    - systemd.service
    - env.example

---

## Phase 1 — Submit Service Implementation

### Goals
- Implement API handlers, storage, and Nomad submission.
- Provide artifact handling and basic auth.

### Concrete Tasks
1) Build FastAPI app
   - app/main.py: create app and include routes
   - app/config.py: load env config (DB URL, Nomad endpoint, artifact config)

2) Storage layer
   - app/storage.py: CRUD for submissions
   - app/models.py: dataclasses or pydantic models
   - Use SQLite for MVP

3) Nomad integration
   - app/nomad_client.py: wrapper around httpx for Nomad API
   - Use existing render logic or reimplement minimal submit job rendering

4) Artifact handling
   - app/artifacts.py: accept upload or store provided URL
   - Option A: POST multipart and upload to S3 (server owns creds)
   - Option B: accept URL only (CLI handles upload)

5) Queue/dispatcher worker
   - app/workers/dispatcher.py: periodic loop
   - Picks queued submissions based on policy
   - Submits Nomad job, updates status

6) API routes
   - app/routes/submissions.py
   - POST /submissions: store request, enqueue
   - GET /submissions: list recent
   - GET /submissions/{id}: detail
   - GET /submissions/{id}/logs: fetch Nomad logs
   - POST /submissions/{id}/cancel: cancel Nomad job and update status

### Proposed File Layout (expanded)
- submit_service/app/
  - main.py
  - config.py
  - models.py
  - storage.py
  - nomad_client.py
  - artifacts.py
  - routes/
    - submissions.py
  - workers/
    - dispatcher.py

---

## Phase 2 — CLI Integration

### Goals
- Preserve CLI surface but point at submit service by default.
- Keep a direct Nomad fallback.

### Concrete Tasks
1) Add submit service config
   - Environment variables: FEDCTL_SUBMIT_ENDPOINT, FEDCTL_SUBMIT_TOKEN
   - Optionally add to fedctl config schema

2) Modify submit commands
   - src/fedctl/commands/submit.py
   - If submit endpoint configured: call service instead of Nomad
   - If --direct flag: use existing direct-Nomad path

3) Add client helper
   - src/fedctl/submit/client.py
   - POST/GET helper with token support

4) Adjust status/logs/ls
   - If endpoint configured: query submit service
   - Keep current behavior if endpoint absent

### Proposed File Layout (changes)
- src/fedctl/submit/
  - client.py (new)
- src/fedctl/commands/submit.py (updated)
- src/fedctl/config/schema.py (updated)

---

## Phase 3 — Tests and Docs

### Goals
- Add tests for new service and CLI integration.
- Document deployment and usage.

### Concrete Tasks
1) Service tests
   - API request/response validation
   - Storage CRUD tests
   - Dispatcher tests with mocked Nomad

2) CLI tests
   - Submit routing to service
   - Status/logs/ls against mock server

3) Docs
   - submit_service/README.md
   - Deployment guide (systemd or docker)
   - Example env config

### Proposed File Layout (docs)
- submit_service/README.md
- submit_service/deployments/systemd.service
- submit_service/deployments/env.example

---

## Phase 4 — Optional Enhancements

### Concrete Tasks
- Fair scheduling policy (priority/quotas)
- Multi-tenant audit log
- Metrics (Prometheus)
- Artifact retention cleanup
- Result storage integration


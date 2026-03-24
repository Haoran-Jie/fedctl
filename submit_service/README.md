# Fedctl Submit Service (MVP)

A lightweight submit server that accepts jobs, stores them in SQLite, and submits them to Nomad.

## Run (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r submit_service/requirements.txt
uvicorn submit_service.app.main:app --reload --host 0.0.0.0 --port 8080
```

## Environment

Copy `submit_service/deployments/env.example` and set values for Nomad and auth.

Repo-config lookup for submit-service:
- If `SUBMIT_REPO_CONFIG` is set, that file is used.
- Otherwise submit-service checks `.fedctl/fedctl_local.yaml` first, then `.fedctl/fedctl.yaml`.

### Internal web UI

The submit service can expose a small server-rendered UI for monitoring and control.

- Enable with `SUBMIT_UI_ENABLED=true`
- Set `SUBMIT_UI_SESSION_SECRET` to a non-empty value
- Optional:
  - `SUBMIT_UI_COOKIE_NAME` (default `fedctl_submit_session`)
  - `SUBMIT_UI_COOKIE_SECURE` (set `true` when served over HTTPS)

The UI is intended for internal CL network / VPN access and supports:
- token login
- submission list/detail
- cancel
- logs / archived logs
- admin nodes page

Project submission still happens through the CLI:

```bash
fedctl submit run /path/to/project
```

## Deployment (systemd)

1) Create a venv and install requirements on the host:

```bash
python -m venv /opt/fedctl/.venv
source /opt/fedctl/.venv/bin/activate
pip install -r /opt/fedctl/submit_service/requirements.txt
```

2) Copy and edit the environment file:

```bash
cp /opt/fedctl/submit_service/deployments/env.example /etc/fedctl-submit.env
```

3) Update `submit_service/deployments/systemd.service` to use the env file path:

```
EnvironmentFile=/etc/fedctl-submit.env
```

4) Install and start the service:

```bash
sudo cp /opt/fedctl/submit_service/deployments/systemd.service /etc/systemd/system/fedctl-submit.service
sudo systemctl daemon-reload
sudo systemctl enable --now fedctl-submit.service
```

5) Verify:

```bash
systemctl status fedctl-submit.service
```

## Deployment (docker)

Example minimal container run (no TLS/auth):

```bash
docker run --rm -p 8080:8080 \
  -e SUBMIT_DB_URL=sqlite:////data/submit.db \
  -e FEDCTL_SUBMIT_ALLOW_UNAUTH=true \
  -e SUBMIT_NOMAD_ENDPOINT=http://nomad.service:4646 \
  -v $(pwd)/submit_service/state:/data \
  ghcr.io/your-org/fedctl-submit:latest
```

### CLI usage

Point the CLI at the submit service:

```bash
export FEDCTL_SUBMIT_ENDPOINT=http://127.0.0.1:8080
export FEDCTL_SUBMIT_TOKEN=token1
export FEDCTL_SUBMIT_USER=alice
```

Token identity/role mapping (recommended):

```bash
export FEDCTL_SUBMIT_TOKEN_MAP='{"token-alice":{"name":"alice","role":"user"},"token-admin":{"name":"ops","role":"admin"}}'
export FEDCTL_SUBMIT_ALLOW_UNAUTH=false
```

Notes:
- `role=user` can access only its own submissions.
- `role=admin` can access/cancel/purge all submissions.
- Keep at least one `role=admin` token if submit-runner should report jobs/results back to the service.
- Legacy `FEDCTL_SUBMIT_TOKENS` still works as admin-only tokens for backward compatibility.

Or configure these in `.fedctl/fedctl.yaml` (env vars still take precedence):

```yaml
submit:
  endpoint: http://127.0.0.1:8080
  token: token1
  user: alice
```

Then submit as usual:

```bash
fedctl submit run /path/to/project --exp demo
fedctl submit status <submission-id>
fedctl submit logs <submission-id>
fedctl submit ls
```

### Artifact handling

The submit service currently expects a pre-uploaded artifact URL (e.g. `s3://...` or `https://...`).
The CLI still performs the upload and passes the URL to the service.

## API

- POST `/v1/submissions`
- GET `/v1/submissions`
- GET `/v1/submissions/{id}`
- GET `/v1/submissions/{id}/logs`
- POST `/v1/submissions/{id}/logs` (runner log archive updates)
- POST `/v1/submissions/{id}/cancel`
- POST `/v1/submissions/purge`
- POST `/v1/submissions/{id}/results`
- POST `/v1/presign` (S3 presigned URL)
- GET `/v1/nodes` (inventory; includes allocations by default; set `include_allocs=false` to skip)

UI routes when enabled:
- GET `/ui/login`
- POST `/ui/login`
- POST `/ui/logout`
- GET `/ui/submissions`
- GET `/ui/submissions/{id}`
- POST `/ui/submissions/{id}/cancel`
- GET `/ui/submissions/{id}/logs`
- GET `/ui/nodes`

Inventory cache TTL can be set with `SUBMIT_NOMAD_INV_TTL` (seconds).
Auto-purge completed Nomad jobs can be set with `SUBMIT_AUTOPURGE_COMPLETED_AFTER` (seconds, `0` disables).

### Queue gating

The dispatcher may set submissions to `blocked` when capacity is insufficient. The reason
is stored in `blocked_reason` and returned by `GET /v1/submissions/{id}`.

### Archived logs fallback

When submit-runner cleanup destroys Nomad jobs, live allocation logs disappear. The runner
now reports a pre-destroy log archive to submit-service, and `GET /v1/submissions/{id}/logs`
falls back to archived logs if live Nomad logs are unavailable.

For grouped jobs:
- `job=supernodes`: select one supernode by `task` or by `index`
- `job=superexec_clientapps`: select one clientapp job by `index`

When live Nomad logs are available, submit-service resolves the stored job mapping first,
then picks the newest allocation that actually contains the requested task. Archived logs
remain the post-cleanup source of truth.

### Example request

```bash
curl -X POST http://127.0.0.1:8080/v1/submissions \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer token1' \\
  -d '{
    "project_name": "mnist",
    "experiment": "mnist-20250125",
    "artifact_url": "s3://bucket/mnist.tar.gz",
    "submit_image": "example/submit:latest",
    "node_class": "submit",
    "args": ["-m", "fedctl.submit.runner", "--path", "mnist"],
    "env": {"FEDCTL_ENDPOINT": "http://10.0.0.5:4646"},
    "priority": 50,
    "namespace": "default"
  }'
```

### Presign request

```bash
curl -X POST http://127.0.0.1:8080/v1/presign \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer token1' \\
  -d '{
    "bucket": "fedctl-submits",
    "key": "fedctl-submits/results/sub-123/model.pth",
    "method": "PUT",
    "expires": 1800
  }'
```

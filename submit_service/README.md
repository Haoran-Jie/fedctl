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
- POST `/v1/submissions/{id}/cancel`

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

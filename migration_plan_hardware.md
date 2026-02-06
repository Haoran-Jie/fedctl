# Migration Plan: Local Laptop -> Hardware Nomad Cluster + Submit Service

This plan describes how to migrate your current local setup to real hardware (RPis + Jetsons) while keeping `fedctl` on your laptop as the user entry point.

**Goals**
1. Run a Nomad cluster across RPis and Jetsons.
2. Run the submit service on a server/device that can reach Nomad.
3. Use `fedctl` on your laptop (and other users’ laptops) to submit jobs remotely via the submit service and Nomad.

**Current Local State (Reference)**
- Nomad runs locally on your laptop (`http://127.0.0.1:4646`).
- Submit service runs locally (`http://127.0.0.1:8080`).
- Repo config in `.fedctl/fedctl.yaml` contains both CLI defaults and submit-service config.
- `fedctl submit run` uses the submit service and S3 presign flow.

---

## 0) Pre‑Migration Checklist

1. **Freeze versions**
- Decide the Nomad version you’ll use on all nodes.
- Decide the `fedctl` version users will install.
- Decide image tags for submit, superexec, and netem.

2. **Inventory and mapping**
- List each RPi/Jetson with hostname, MAC, planned IP, and device type (`rpi` or `jetson`).
- Decide which nodes will be Nomad servers vs clients.

3. **Network readiness**
- Confirm LAN subnet, switch ports, cabling.
- Decide stable addressing: static IP, DHCP reservations, or DNS names.
- Decide what is public (submit service) vs private (Nomad API, RPC).

4. **Security and access**
- Decide if Nomad ACLs are enabled.
- Decide submit service auth tokens and distribution.
- Decide whether users must use VPN (Tailscale/WireGuard) or trusted LAN only.

5. **S3 / artifact storage**
- Confirm bucket exists and is reachable from submit service host.
- Prepare AWS creds for submit service host if using presign.

6. **Config migration plan**
- Identify what stays on laptop: `.fedctl/fedctl.yaml`, `~/.config/fedctl/config.toml`.
- Identify what moves to servers: Nomad HCLs, submit service env + systemd unit.

7. **Repo config sanity**
- Ensure `.fedctl/fedctl.yaml` matches hardware device types.
- Ensure `deploy.network.image` is reachable from all nodes.
- Update `submit.endpoint` to planned submit service URL.

8. **Backup local state**
- Save `.fedctl/fedctl.yaml` and `~/.config/fedctl/config.toml`.
- Save any local submit service env or notes.

9. **Access to devices**
- Verify SSH access to every node.
- Ensure time sync (NTP) and correct system clock.

---

## 1) Target Topology

**Nomad cluster**
- 1 to 3 Nomad servers.
- Multiple Nomad clients on RPis and Jetsons.
- All nodes are on the same LAN (Ethernet + switch).

**Submit service** run on the same rpi 

- Runs on a server or a stable device (could be the Nomad server node, or a separate VM/device).
- Must reach the Nomad server API.
- Does not need to be part of the Nomad cluster.

**Laptop user**

- Runs `fedctl` and submits jobs remotely to submit service endpoint.
- Does not need direct access to Nomad if submit service is used.

---

## 2) Network Requirements and Exposure

**LAN requirements**
- All RPis and Jetsons must be on the same L2/L3 network segment.
- Nomad servers and clients must be able to reach each other on Nomad ports.
- Submit service must reach the Nomad server API.

**Recommended exposure policy**
- Do not expose Nomad ports publicly.
- Expose submit service endpoint only to authorized users, ideally behind VPN or TLS.
- Prefer Tailscale, WireGuard, or SSH tunnels for remote access.

**Ports and their purpose**
- Nomad HTTP API: `4646` (server). Should be private.
- Nomad RPC: `4647` (server). Private.
- Nomad Serf: `4648` (server + clients). Private.
- Submit service HTTP API: `8080` (public or VPN-only).
- SuperLink/SuperExec/SuperNode app ports (9091–9094). Private within cluster.

---

## 3) Nomad Cluster Setup (RPi + Jetson)

**Step 3.1: Install Nomad on all devices (RPi + Jetson)**

Below is a reproducible, SSH‑friendly install sequence. Use the **same** `NOMAD_VERSION` on every node (servers and clients).

1. **SSH into a node and run:**

```bash
sudo apt-get update
sudo apt-get install -y curl unzip ca-certificates

# Choose one version and use it on every node.
export NOMAD_VERSION="1.11.1"

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) NOMAD_ARCH="arm64" ;;
  armv7l|armv7)  NOMAD_ARCH="arm" ;;
  x86_64|amd64)  NOMAD_ARCH="amd64" ;;
  *) echo "Unsupported arch: $ARCH" && exit 1 ;;
esac

TMP_DIR="$(mktemp -d)"
cd "$TMP_DIR"
curl -fsSLO "https://releases.hashicorp.com/nomad/${NOMAD_VERSION}/nomad_${NOMAD_VERSION}_linux_${NOMAD_ARCH}.zip"
unzip -o "nomad_${NOMAD_VERSION}_linux_${NOMAD_ARCH}.zip"
sudo install -m 0755 nomad /usr/local/bin/nomad
nomad version
```

2. **(Optional) Verify checksum**

```bash
cd "$TMP_DIR"
curl -fsSLO "https://releases.hashicorp.com/nomad/${NOMAD_VERSION}/nomad_${NOMAD_VERSION}_SHA256SUMS"
grep "nomad_${NOMAD_VERSION}_linux_${NOMAD_ARCH}.zip" nomad_${NOMAD_VERSION}_SHA256SUMS | sha256sum -c -
```

3. **Repeat on every node**

Run the same steps on all RPis and Jetsons so all servers and clients run the identical Nomad version.

**Step 3.2: Choose server nodes**

- Use 1 server for simple dev setups.
- Use 3 servers for high availability (odd quorum).

**Step 3.3: Configure Nomad server HCL**

Draft `server.hcl` template (replace LAN IPs and datacenter name):

```hcl
datacenter = "dc1"
data_dir   = "/opt/nomad/data"

bind_addr = "0.0.0.0"

advertise {
  http = "192.168.1.10:4646"
  rpc  = "192.168.1.10:4647"
  serf = "192.168.1.10:4648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

ui {
  enabled = true
}

# Optional: enable ACLs later
# acl {
#   enabled = true
# }
```

Steps to place and start the server (SSH into the server node):

1. Create directories and config:

```bash
sudo mkdir -p /etc/nomad.d /opt/nomad/data
sudo tee /etc/nomad.d/server.hcl > /dev/null <<'EOF'
datacenter = "dc1"
data_dir   = "/opt/nomad/data"

bind_addr = "0.0.0.0"

advertise {
  http = "192.168.1.10:4646"
  rpc  = "192.168.1.10:4647"
  serf = "192.168.1.10:4648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

ui {
  enabled = true
}
EOF
```

2. Start Nomad server manually (good for quick testing):

```bash
sudo nomad agent -config=/etc/nomad.d/server.hcl
```

3. Start Nomad server as a systemd service (recommended):

```bash
sudo tee /etc/systemd/system/nomad.service > /dev/null <<'EOF'
[Unit]
Description=Nomad
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/nomad agent -config=/etc/nomad.d/server.hcl
Restart=on-failure
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nomad
sudo systemctl status nomad
```

**Step 3.4: Configure Nomad client HCL**
- On each RPi/Jetson, configure `client.hcl` with:
- `client { enabled = true }`
- `servers = ["<server-ip>:4647"]`
- `node_class = "node"` for worker nodes.
- `meta` tags to describe hardware, for example:
- `meta { device_type = "rpi" }` on RPis.
- `meta { device_type = "jetson" }` on Jetsons.

**Step 3.5: Systemd services**
- Install systemd units for Nomad server and clients.
- Enable and start Nomad on boot.

**Step 3.6: Validate cluster**
- From the server, confirm nodes are `ready`.
- From any node on LAN, `nomad node status` shows RPi + Jetson clients.

---

## 4) Submit Service Deployment (Server or Device)

**Step 4.1: Choose host**
- Host must reach Nomad server API.
- Should have stable IP or DNS.

**Step 4.2: Create service env file**
- Use `submit_service/deployments/env.example` as base.
- Populate at least:
- `SUBMIT_DB_URL`
- `SUBMIT_NOMAD_ENDPOINT` (LAN IP of Nomad server)
- `FEDCTL_SUBMIT_TOKENS` and/or `FEDCTL_SUBMIT_ALLOW_UNAUTH`
- `SUBMIT_DISPATCH_MODE=queue` (your current config)

**Step 4.3: Run submit service**
- Run via Uvicorn or systemd with `submit_service/app/main.py`.
- Expose port `8080` only to trusted users or VPN.

**Step 4.4: Optional S3 presign support**
- If using `s3+presign://`, install `boto3` and configure AWS creds on this submit service host.
- Set `AWS_REGION` or `AWS_DEFAULT_REGION`.

---

## 5) Repo Config and Env Var Placement

**Repo config (.fedctl/fedctl.yaml)**
- Lives in each project repo.
- This file is used by the CLI on users’ laptops and also optionally by the submit service.
- Keep both `submit` and `deploy` sections here.

**Submit service config**
- Source of truth should be environment variables on the submit service host.
- The `submit-service` section in `.fedctl/fedctl.yaml` is only read by submit service when `SUBMIT_REPO_CONFIG` is set.
- Recommended: do not rely on repo file for submit service in production.

**Laptop config**
- `~/.config/fedctl/config.toml` still lives on each user’s laptop.
- User profile should point to the submit service endpoint.
- Repo config stays with the project.

**What moves off your laptop**
- Nomad server/client HCL files are on the hardware nodes.
- Submit service env file and service unit live on submit service host.
- ACL tokens and Nomad server state live on the cluster.

---

## 6) Configuration Mapping

**Your current .fedctl/fedctl.yaml fields**
- `submit.endpoint` should become the **public or VPN** submit service URL.
- `submit.token` should match `FEDCTL_SUBMIT_TOKENS` on the service.
- `submit-service.nomad_endpoint` should be the **LAN** Nomad server IP.
- `deploy.network.image` must be reachable from all Nomad clients (RPi/Jetson).

**Nomad client metadata**
- RPi nodes must have `meta.device_type = "rpi"`.
- Jetson nodes must have `meta.device_type = "jetson"`.
- These are required for `deploy.supernodes` typed placement to work.

---

## 6.1) Docker Images and Registry Strategy (Critical for Hardware Migration)

Your stack uses **multiple Docker images** that must be accessible to all Nomad clients (RPi + Jetson). You should decide **where images are built**, **where they are stored**, and **how nodes authenticate**.

### Images in use
1. **Submit runner image**  
   - From `.fedctl/fedctl.yaml`: `submit.image`  
   - Example: `jiahborcn/fedctl-submit:latest`

2. **SuperExec image** (built from your Flower project)  
   - Built by `fedctl build` or inside the submit runner job.  
   - Tagged using `image_registry` in repo config if set.

3. **SuperNode image**  
   - Defaults to `flwr/supernode:<version>` or a generated netem‑enabled supernode image if `--net` profiles are used.

4. **Netem image**  
   - From `.fedctl/fedctl.yaml`: `deploy.network.image`  
   - Example: `jiahborcn/netem:latest`

### Decide a registry
All nodes must be able to **pull** these images. You have three realistic options:

- **Public Docker Hub / GHCR**  
  - Simple, but requires images to be public or nodes to have credentials.

- **Private registry (recommended for stability)**  
  - Run a registry on your LAN (e.g., `registry.local:5000`) or use a private org registry.
  - Requires `docker login` on each Nomad client host.

- **Build locally on each node**  
  - Not recommended. Slower and inconsistent across nodes.

### Recommended approach
1. **Build and push images from your laptop or CI**  
   - SuperExec images should be built once and pushed to your registry.
   - The submit runner then uses that tag.

2. **Set `image_registry` in `.fedctl/fedctl.yaml`**  
   - Example:  
     ```yaml
     image_registry: registry.local:5000
     ```
   - `fedctl build` will tag/push using this registry.

3. **Authenticate on every Nomad client**  
   - Run `docker login` on each RPi/Jetson if the registry is private.

### Cluster default registry (even if repo config is missing)
If a user’s repo does **not** set `image_registry`, set a cluster‑wide default via env:

```bash
export FEDCTL_IMAGE_REGISTRY="registry.local:5000"
```

Set this on:
- The submit service host (so submit runner builds tag to the registry)
- Any build hosts/laptops that build images

This ensures **all images default to `registry.local:5000`** even when the repo config omits `image_registry`.

### Multi‑arch considerations (RPi + Jetson)
RPis are typically **arm64/arm**, Jetsons are **arm64**, so you must ensure images exist for these architectures.

Use `docker buildx` to push multi‑arch images:\n
```bash
docker buildx build \\
  --platform linux/arm64,linux/arm/v7 \\
  -t registry.local:5000/your-image:tag \\
  --push .
```

### Nomad client setup impact
Nomad pulls images using Docker on each client host. That means:
- The Docker daemon on each node must be able to reach the registry.
- If using a private registry, credentials must exist on **each node**.

---

## 6.2) Multi‑Node Image Publishing Requirements (Problems + Fixes)

### The problem (multi‑node)
- The **submit runner** builds the SuperExec image *locally* on the node where the submit batch job runs.
- `fedctl deploy` then schedules SuperExec jobs on other Nomad clients.
- If the image was not pushed to a registry, those nodes cannot pull it → **allocation fails**.

### Same issue with netem‑enabled supernode image
- When `--net` is used, `run_deploy` may build a netem‑enabled supernode image *locally*.
- If SuperNode allocations land on other nodes, they must pull the image.
- If it isn’t pushed, they fail for the same reason.

### Recommended fixes
1. **Always push images in multi‑node mode.**
2. **Use a single registry for the whole cluster** (public or private).
3. **Ensure every Nomad client can pull from it** (credentials if private).

### Example commands: SuperExec image (build + push)

Use `buildx` to build multi‑arch and push to your registry:

```bash
# Run on a machine with buildx + Docker access
export REGISTRY="registry.local:5000"
export IMAGE_NAME="yourproj-superexec"
export TAG="$(git rev-parse --short HEAD)"

docker buildx build \\
  --platform linux/arm64,linux/arm/v7 \\
  -t ${REGISTRY}/${IMAGE_NAME}:${TAG} \\
  --push .
```

Then in `.fedctl/fedctl.yaml`:

```yaml
image_registry: registry.local:5000
```

And when submitting from laptop:

```bash
fedctl submit run . --push --image ${REGISTRY}/${IMAGE_NAME}:${TAG}
```

### Example commands: Netem supernode image (build + push)

```bash
export REGISTRY="registry.local:5000"
export FLWR_VERSION="1.25.0"

# Build the Dockerfile that fedctl would generate
fedctl build --flwr-version ${FLWR_VERSION} --image ${REGISTRY}/flwr-supernode-netem:${FLWR_VERSION} --push
```

If you prefer to build directly with Docker:

```bash
docker buildx build \\
  --platform linux/arm64,linux/arm/v7 \\
  -t ${REGISTRY}/flwr-supernode-netem:${FLWR_VERSION} \\
  --push path/to/netem/Dockerfile/context
```

### Operational rule of thumb
If a Nomad allocation can land on a different host, **the image must be in a shared registry**, not just local to the submit runner host.

---

## 7) User Workflow (Remote Submission)

**User installs fedctl**
- Use pipx or pip to install the latest `fedctl` version.
- Ensure version matches the server and job spec expectations.

**User config**
- Set `FEDCTL_SUBMIT_ENDPOINT` or use `.fedctl/fedctl.yaml` `submit.endpoint`.
- Set `FEDCTL_SUBMIT_TOKEN` or use repo config `submit.token`.

**User submit**
- `fedctl submit run <project>` uploads artifacts and submits to submit service.
- Submit runner is scheduled in Nomad and calls back to submit service.

---

## 8) Detailed Migration Steps (Implementation Plan)

1. **Prepare LAN and addressing**
- Assign static IPs or DHCP reservations for Nomad servers and submit service host.
- Verify all nodes can reach each other by IP.

2. **Install Nomad on all nodes**
- Use the Step 3.1 install script on each device.
- Ensure the exact same `NOMAD_VERSION` on servers and clients.

3. **Configure Nomad server(s)**
- Use the Step 3.3 template and commands on each server node.
- If you run multiple servers, set `bootstrap_expect` to 3 and update the `advertise` addresses per node.

4. **Configure Nomad clients on RPis/Jetsons**
- Create `client.hcl` with server list.
- Set `node_class = "node"`.
- Set `meta.device_type` for each hardware type.
- Start client services.

5. **Verify Nomad cluster health**
- `nomad server members` shows all servers.
- `nomad node status` shows all clients.

6. **Deploy submit service**
- Copy env file and set required vars.
- Start service with systemd.

7. **Update repo config**
- Update `.fedctl/fedctl.yaml` `submit.endpoint` to the real submit service URL.
- Update `submit-service.endpoint` only if submit service will read repo config.
- Ensure `deploy.network.image` is reachable from RPi/Jetson nodes.

8. **Update users’ laptop configs**
- Each user sets `FEDCTL_SUBMIT_ENDPOINT` or uses repo config.
- Each user sets `FEDCTL_SUBMIT_TOKEN` or uses repo config.

9. **Test end-to-end**
- `fedctl submit run` from laptop.
- Check submit service logs.
- Check Nomad jobs and allocations.
- Check `fedctl submit logs`.

---

## 9) Security and Access Control

- Keep Nomad API private to LAN or VPN.
- Restrict submit service endpoint with tokens and TLS.
- Use Nomad ACLs for production use.
- Avoid exposing RPi/Jetson nodes to the public internet.

---

## 10) Validation Checklist

- Nomad server reachable from submit service host.
- Nomad clients registered with correct `node_class` and `meta.device_type`.
- Submit service returns `200` on `/v1/submissions` with your token.
- `fedctl submit run` schedules a submit runner job.
- SuperLink/SuperExec/SuperNode jobs are deployed and reachable within LAN.
- Results upload completes (S3 presign works).

---

## 11) Notes on S3 Presign Usage

### Presign flow (recommended)
If you use `s3+presign://` and let the **submit service** generate presigned URLs:

1. **Submit service must have AWS credentials**  
   The service signs presigned URLs using `boto3`, so the credentials must live on the **submit service host**, not on your laptop.

2. **Where to put credentials on the submit service host**  
   Choose one of these methods:
   - **Environment variables** (simple and explicit):
     - `AWS_ACCESS_KEY_ID`
     - `AWS_SECRET_ACCESS_KEY`
     - `AWS_SESSION_TOKEN` (optional)
     - `AWS_REGION` or `AWS_DEFAULT_REGION`
   - **Shared credentials file**:
     - `/home/<user>/.aws/credentials`
     - `/home/<user>/.aws/config`
   - **Instance role / IAM role** (if running on AWS): no static keys needed.

3. **Submit service env settings**  
   - `AWS_REGION` or `AWS_DEFAULT_REGION` must be set.
   - If using an S3‑compatible endpoint (MinIO, etc.), set `AWS_S3_ENDPOINT`.

4. **Permissions (minimum)**  
   The credentials used for signing should allow:
   - `s3:PutObject` on the target bucket/prefix  
   - `s3:GetObject` on the target bucket/prefix  
   (You can scope this down to `fedctl-submits/*` or similar.)

5. **Who needs creds**  
   - **Submit service host**: Yes (for presign).  
   - **User laptops**: No (they only call the submit service).  
   - **Nomad runners**: No (they upload using presigned URLs).

### Direct S3 upload (not using presign)
If you skip presign and use `s3://` directly, then AWS credentials must be available to the **submit runner job** (passed via env). That’s less secure and harder to manage.

---

## 12) Recommended File Locations

- Nomad server config: `/etc/nomad.d/server.hcl`
- Nomad client config: `/etc/nomad.d/client.hcl`
- Submit service env: `/etc/fedctl-submit.env`
- Submit service systemd unit: `/etc/systemd/system/fedctl-submit.service`
- Repo config: `<project>/.fedctl/fedctl.yaml`
- User config: `~/.config/fedctl/config.toml`

---

## 13) Concrete Implementation Phases (Detailed)

This is a step‑by‑step, follow‑later sequence that matches the current plan and our chat decisions:
- GL.iNet stays in **router/NAT mode** for isolation.
- Only the submit service is exposed to the upstream “flower network” via **port forwarding**.
- 4 RPis with roles: server+submit-service, submit client, link client, node client.

### Phase 0 — Inventory + Network Decisions (1–2 hours)
**Goal:** lock topology and network access model.

1. Decide final roles + IP mapping (example):
   - RPi‑A: Nomad server + submit service (LAN: `192.168.8.10`)
   - RPi‑B: Nomad client `node_class=submit` (LAN: `192.168.8.11`)
   - RPi‑C: Nomad client `node_class=link` (LAN: `192.168.8.12`)
   - RPi‑D: Nomad client `node_class=node` + `device_type=rpi` (LAN: `192.168.8.13`)
2. Confirm GL.iNet mode is **router/NAT**.
3. Set static DHCP leases on GL.iNet for all RPis.
4. Decide how upstream users will reach submit:
   - Port forward TCP `8080` on GL.iNet WAN -> RPi‑A `192.168.8.10:8080`.
5. Confirm each RPi has internet access (`sudo apt update` on each).

**Deliverables:**
- Final IP table and device roles.
- GL.iNet DHCP reservations.
- Port forwarding plan.

**Phase 0 Log (what we actually did)**
- Set GL.iNet DHCP range to `192.168.8.100`–`192.168.8.249` and created DHCP reservations.
- Final RPi IP + role mapping:
- rpi1 `192.168.8.101` → Nomad server + submit service
- rpi2 `192.168.8.102` → submit client
- rpi3 `192.168.8.103` → link client
- rpi4 `192.168.8.104` → node client (`device_type=rpi`)
- Confirmed GL.iNet is in router/NAT mode.
- WAN IP observed: `10.100.2.142`.
- Enabled GL.iNet DDNS (host: `vw8d5a0.glddns.com`).
- Planned submit endpoint for flower network users: `http://vw8d5a0.glddns.com:8080`.
- Planned port forward: TCP `8080` WAN → `192.168.8.101:8080` (not yet executed at time of log).
- Rebooted RPis to apply DHCP reservations.

---

### Phase 1 — Base OS + Nomad Install (2–3 hours)
**Goal:** all RPis run the same Nomad version.

1. SSH into each RPi and install Nomad (Step 3.1 above).
2. Verify `nomad version` matches across all nodes.
3. Ensure time sync is correct (NTP).

**Deliverables:**
- Nomad installed on all 4 RPis.
- Same version everywhere.

**Phase 1 Log (what we actually did)**
- Installed Nomad on all RPis using:
```bash
sudo apt-get update
sudo apt-get install -y curl unzip ca-certificates

export NOMAD_VERSION="1.11.1"

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) NOMAD_ARCH="arm64" ;;
  armv7l|armv7)  NOMAD_ARCH="arm" ;;
  x86_64|amd64)  NOMAD_ARCH="amd64" ;;
  *) echo "Unsupported arch: $ARCH" && exit 1 ;;
esac

TMP_DIR="$(mktemp -d)"
cd "$TMP_DIR"
curl -fsSLO "https://releases.hashicorp.com/nomad/${NOMAD_VERSION}/nomad_${NOMAD_VERSION}_linux_${NOMAD_ARCH}.zip"
unzip -o "nomad_${NOMAD_VERSION}_linux_${NOMAD_ARCH}.zip"
sudo install -m 0755 nomad /usr/local/bin/nomad
nomad version
```
- Verified Nomad version: `1.11.1` on at least one node.
- rpi1 server config created at `/etc/nomad.d/server.hcl`:
```hcl
datacenter = "dc1"
data_dir   = "/opt/nomad/data"

bind_addr = "0.0.0.0"

advertise {
  http = "192.168.8.101:4646"
  rpc  = "192.168.8.101:4647"
  serf = "192.168.8.101:4648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

ui {
  enabled = true
}
```
- rpi1 systemd unit created at `/etc/systemd/system/nomad.service`:
```ini
[Unit]
Description=Nomad
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/nomad agent -config=/etc/nomad.d/server.hcl
Restart=on-failure
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```
- Started rpi1 server:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nomad
nomad server members
```
- Client configs created on rpi2/rpi3/rpi4 at `/etc/nomad.d/client.hcl` (with Docker allow_caps):
```hcl
datacenter = "dc1"
data_dir   = "/opt/nomad/data"
bind_addr  = "0.0.0.0"

client {
  enabled    = true
  servers    = ["192.168.8.101:4647"]
  node_class = "<submit|link|node>"

  meta {
    device_type = "<submit|link|rpi>"
  }

  # Only on submit node (rpi2)
  host_volume "docker-socket" {
    path      = "/var/run/docker.sock"
    read_only = false
  }
}

plugin "docker" {
  config {
    allow_caps = [
      "audit_write",
      "chown",
      "dac_override",
      "fowner",
      "fsetid",
      "kill",
      "mknod",
      "net_admin",
      "net_bind_service",
      "net_raw",
      "setfcap",
      "setgid",
      "setpcap",
      "setuid",
      "sys_chroot"
    ]
  }
}
```
- Client systemd unit created on rpi2/rpi3/rpi4 at `/etc/systemd/system/nomad.service`:
```ini
[Unit]
Description=Nomad
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/nomad agent -config=/etc/nomad.d
Restart=on-failure
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```
- rpi2 needed Docker because of the docker socket volume. Installed Docker on rpi2:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
sudo systemctl restart nomad
```
- Verified all three clients registered:
```bash
nomad node status
```
Result included:
- rpi2 `submit` ready
- rpi3 `link` ready
- rpi4 `node` ready

- Noted Nomad UI reported unhealthy `exec` and `java` drivers (ignored for now unless needed).
- Determined Docker is required on rpi3 and rpi4 for Docker-based jobs (SuperLink/SuperNode/SuperExec).

---

### Phase 2 — Nomad Server Bring‑Up (1 hour)
**Goal:** stable server with UI/API.

1. On RPi‑A, create `/etc/nomad.d/server.hcl` based on the template.
2. Set `advertise` to RPi‑A LAN IP (`192.168.8.10`).
3. Start server via systemd and verify status.
4. From RPi‑A, run `nomad server members`.

**Deliverables:**
- Nomad server running on RPi‑A.
- `nomad server members` shows 1 server.

**Status:** Completed (rpi1 server running, `nomad server members` shows leader).

---

### Phase 3 — Nomad Clients (Submit/Link/Node) (2–3 hours)
**Goal:** all clients registered with correct `node_class` and `meta.device_type`.

1. Create `/etc/nomad.d/client.hcl` on each client RPi.
2. Use `servers = ["192.168.8.10:4647"]`.
3. Set per‑node classes:
   - RPi‑B: `node_class = "submit"` and `meta.device_type = "submit"`.
   - RPi‑C: `node_class = "link"` and `meta.device_type = "link"`.
   - RPi‑D: `node_class = "node"` and `meta.device_type = "rpi"`.
4. For the submit node, add host volume for Docker socket:
   - `host_volume "docker-socket" { path = "/var/run/docker.sock" read_only = false }`
5. Start clients and confirm `nomad node status`.

**Deliverables:**
- All clients show `ready`.
- Node classes and device types correct in `nomad node status -verbose`.

**Status:** Completed (rpi2 submit, rpi3 link, rpi4 node all `ready`).

---

### Phase 4 — Submit Service Deployment (1–2 hours)
**Goal:** submit service online on RPi‑A.

1. Prepare env file from `submit_service/deployments/env.example`.
2. Set:
   - `SUBMIT_NOMAD_ENDPOINT=http://192.168.8.10:4646`
   - `FEDCTL_SUBMIT_TOKENS=<token>` (or allow unauth for dev)
   - DB URL and dispatch mode as needed.
3. Start submit service (systemd or uvicorn).
4. Verify locally on RPi‑A: `curl http://127.0.0.1:8080/v1/health` (or list endpoint).

**Deliverables:**
- Submit service running on RPi‑A.
- Local health check succeeds.

---

### Phase 5 — Router Exposure (30–60 min)
**Goal:** expose only submit service to upstream flower network.

1. In GL.iNet, configure port forwarding:
   - TCP `8080` WAN -> `192.168.8.10:8080`.
2. From a device on the upstream flower network, test:
   - `curl http://<GLI_NET_WAN_IP>:8080/v1/health`
3. Confirm other internal RPi ports are not reachable upstream.

**Deliverables:**
- Submit service reachable from upstream.
- Other devices remain isolated.

---

### Phase 6 — Repo + Client Config (1 hour)
**Goal:** `fedctl` on laptop points to submit service.

1. Update `.fedctl/fedctl.yaml`:
   - `submit.endpoint = http://<GLI_NET_WAN_IP>:8080`
   - `submit.token = <token>`
2. Ensure submit service uses env as source of truth.
3. If using multi‑arch images, set `image_registry` to a shared registry.

**Deliverables:**
- `fedctl submit ls` works from laptop.

---

### Phase 7 — End‑to‑End Validation (1–2 hours)
**Goal:** prove scheduling works across all roles.

1. From laptop, run:
   - `fedctl submit inventory`
   - `fedctl submit run <project>`
2. Check:
   - Submit runner lands on `node_class=submit`.
   - SuperLink lands on `node_class=link`.
   - SuperNodes land on `node_class=node`.
3. Confirm logs and artifacts flow correctly.

**Deliverables:**
- Full job pipeline works.
- Inventory shows correct device types and usage.

---

### Phase 8 — Hardening + Quality of Life (optional)
**Goal:** stability and security.

1. Enable TLS for submit service.
2. Add firewall rules on GL.iNet to allow only `8080` inbound.
3. Set Nomad ACLs if needed.
4. Configure a private registry for images.

**Deliverables:**
- Stable, secure, repeatable environment.

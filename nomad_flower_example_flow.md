# Example: Running Flower Fabric on Nomad (SuperLink + SuperNodes + SuperExec)

*Generated: 2026-01-19*

This note explains the **end-to-end flow** of the example run you described:

- Start a **Nomad server** and multiple **Nomad clients** using HCL agent configs.
- Submit Nomad jobs for Flower Fabric components (**SuperLink**, **SuperNodes**, and **SuperExec** apps).
- Discover the **SuperLink control API address** from the running allocation.
- Point a Flower app (via `pyproject.toml`) at that address under a federation named `remote-deployment`.
- Run the experiment from the user machine with `flwr run ... --stream`.

It also includes the full content of all provided `*.hcl` files for reference.

---

## 1) What you are deploying

### Nomad layer
- **Nomad server**: the control plane (scheduling + API).
- **Nomad clients**: worker nodes where jobs actually run.

You start these with:
```bash
nomad agent -config=server.hcl
nomad agent -config=client1.hcl
nomad agent -config=client2.hcl
nomad agent -config=client3.hcl
```

### Flower Fabric layer (as Nomad jobs)
- **SuperLink**: the coordination/control component that SuperNodes and SuperExec connect to.
- **SuperNode(s)**: worker-side Flower runtime nodes that provide execution capacity (and may expose ClientApp IO depending on config).
- **SuperExec**: runs your Flower **ServerApp** and **ClientApp** containers.

Submitted as Nomad jobs:
```bash
nomad job run superlink.hcl
nomad job run supernode1.hcl
nomad job run supernode2.hcl
nomad job run superexec_serverapp.hcl
nomad job run superexec_clientapp1.hcl
nomad job run superexec_clientapp2.hcl
```

---

## 2) High-level sequence (why these steps are in this order)

1) **Start Nomad server + clients**  
   This creates a cluster where workloads can be scheduled.

2) **Start SuperLink first**  
   SuperLink is the rendezvous point. SuperNodes and SuperExec apps need its address.

3) **Start SuperNodes**  
   SuperNodes register/attach to SuperLink and prepare the runtime to accept app execution.

4) **Start SuperExec jobs (serverapp/clientapp)**  
   These are the workloads that run your Flower **ServerApp** and **ClientApp** processes/containers.
   They also connect to SuperLink/SuperNodes according to the job config.

5) **Discover SuperLink address and set Flower federation**  
   Your local Flower app needs a `remote-deployment` target. That target is the SuperLink address.

6) **Run from the user machine with Flower CLI**  
   `flwr run ... remote-deployment --stream` connects to the remote Fabric deployment and streams logs/output.

---

## 3) Getting the SuperLink control API address

After `nomad job run superlink.hcl`, inspect the job status to find its allocation:

```bash
nomad job status superlink
```

From the output, grab the allocation ID (example placeholder):

```bash
nomad alloc status 8081a9cc
```

In the allocation status output, look for the **network address/port** that corresponds to the SuperLink service (often exposed as a mapped port).

That final value is what you put into the Flower federation config as:

```
HOST:PORT
```

Example:
```
10.3.192.52:27738
```

> Why this matters: `flwr run` needs to know “where the remote federation lives”. In this setup, that’s the SuperLink endpoint that routes coordination between server/client apps and nodes.

---

## 4) The Flower app side: Docker image + `pyproject.toml`

### 4.1 Dockerfile used for SuperExec app images

In your “ideal usecase”, the Flower app image is based on `flwr/superexec` and installs the local project into the container:

```Dockerfile
FROM flwr/superexec:1.25.0

# This is where the Flower app will live inside the container
WORKDIR /tmp

# Copy project metadata and code into the image
# Assumes pyproject.toml is in this directory and code is under src/ or similar.
COPY pyproject.toml ./
COPY . .

# Optional: remove flwr[simulation] extra from pyproject if present (like the tutorial does)
# The '|| true' prevents the build from failing if that line doesn't exist.
RUN sed -i 's/.*flwr\[simulation\].*//' pyproject.toml || true \
    && python -m pip install -U --no-cache-dir .

# Match the tutorial: SuperExec entrypoint
ENTRYPOINT ["flower-superexec"]

```

### 4.2 `pyproject.toml` federation stanza

Your Flower app repo includes a federation target named `remote-deployment`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sklearnexample"
version = "1.0.0"
description = "Federated Learning with scikit-learn and Flower (Quickstart Example)"
license = "Apache-2.0"
dependencies = [
    "flwr[simulation]>=1.22.0",
    "flwr-datasets[vision]>=0.5.0",
    "scikit-learn>=1.6.1",
]

[tool.hatch.build.targets.wheel]
packages = ["."]

[tool.flwr.app]
publisher = "flwrlabs"

[tool.flwr.app.components]
serverapp = "sklearnexample.server_app:app"
clientapp = "sklearnexample.client_app:app"

[tool.flwr.app.config]
penalty = "l2"
num-server-rounds = 5
min-available-clients = 2

[tool.flwr.federations]
default = "remote-deployment"

[tool.flwr.federations.local-simulation]
options.num-supernodes = 3

[tool.flwr.federations.remote-deployment]
address = "10.3.192.52:27738"
insecure = true

```

Key points:
- `default = "remote-deployment"` means `flwr run` will use it unless you override.
- `address = "10.3.192.52:27738"` is the **SuperLink address** you discovered from the Nomad allocation.
- `insecure = true` means the connection is not using TLS verification (fine for a PoC; for a shared lab you’d likely switch to TLS later).

---

## 5) Running the workload

Once the Fabric deployment is up and `pyproject.toml` points to the right SuperLink address:

```bash
flwr run quickstart-sklearn-tabular --stream
```

What happens under the hood (conceptually):
1) Flower CLI reads `pyproject.toml` and selects the `remote-deployment` federation.
2) It connects to the SuperLink address.
3) SuperLink coordinates with SuperNodes and SuperExec instances to run the ServerApp + ClientApps.
4) `--stream` streams logs back to the user terminal as the run progresses.

---

## 6) Troubleshooting checklist

### Nomad
- `nomad status` shows server leader and healthy clients.
- `nomad node status` shows clients are ready.
- `nomad job status <job>` shows allocations are running.
- If a job is stuck pending: check constraints/resources and client availability.

### Flower
- If `flwr run` can’t connect: re-check the federation address from `nomad alloc status`.
- If address is correct but unreachable: ensure the correct network path (same LAN, or VPN/Tailscale subnet route in the future).

---

# Appendix A — HCL files (full context)

Below are the exact contents of the HCL configs and job specs used in the flow above.

## `server.hcl`

```hcl
data_dir = "/Users/samueljie/nomad-data/server"
bind_addr = "127.0.0.1"

advertise {
  http = "127.0.0.1:4646"
  rpc  = "127.0.0.1:4647"
  serf = "127.0.0.1:4648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

client {
  enabled = false
}
```

## `client1.hcl`

```hcl
data_dir = "/Users/samueljie/nomad-data/client1"
bind_addr = "0.0.0.0"

advertise {
  http = "127.0.0.1:5656"
  rpc  = "127.0.0.1:5657"
  serf = "127.0.0.1:5658"
}

ports {
  http = 5656
  rpc  = 5657
  serf = 5658
}

client {
  enabled = true
  servers = ["127.0.0.1:4647"]
  node_class = "link"
  network_interface = "en0"

  gc_interval = "10m"
  gc_max_allocs = 200
}
```

## `client2.hcl`

```hcl
data_dir = "/Users/samueljie/nomad-data/client2"
bind_addr = "0.0.0.0"

advertise {
  http = "127.0.0.1:5756"
  rpc  = "127.0.0.1:5757"
  serf = "127.0.0.1:5758"
}

ports {
  http = 5756
  rpc  = 5757
  serf = 5758
}

client {
  enabled = true
  servers = ["127.0.0.1:4647"]
  node_class = "node"
  network_interface = "en0"

  gc_interval = "10m"
  gc_max_allocs = 200
}
```

## `client3.hcl`

```hcl
data_dir = "/Users/samueljie/nomad-data/client3"
bind_addr = "0.0.0.0"

advertise {
  http = "127.0.0.1:5856"
  rpc  = "127.0.0.1:5857"
  serf = "127.0.0.1:5858"
}

ports {
  http = 5856
  rpc  = 5857
  serf = 5858
}

client {
  enabled = true
  servers = ["127.0.0.1:4647"]
  node_class = "node"
  network_interface = "en0"

  gc_interval = "10m"
  gc_max_allocs = 200
}
```

## `superlink.hcl`

```hcl
job "superlink" {
  datacenters = ["dc1"]
  type = "service"

  constraint {
    attribute = "${node.class}"
    operator  = "="
    value     = "link"
  }

  group "superlink" {

    network {
      port "serverappio" {}
      port "fleet" {}
      port "control" {}
    }

    service {
      name     = "superlink-serverappio"
      port     = "serverappio"
      provider = "nomad"
    }
    service {
      name     = "superlink-fleet"
      port     = "fleet"
      provider = "nomad"
    }
    service {
      name     = "superlink-control"
      port     = "control"
      provider = "nomad"
    }

    task "superlink" {
      driver = "docker"

      config {
        image = "flwr/superlink:1.25.0"
        ports = ["serverappio", "fleet", "control"]
        args = [
          "--insecure",
          "--isolation", "process",
          "--serverappio-api-address", "0.0.0.0:${NOMAD_PORT_serverappio}",
          "--fleet-api-address", "0.0.0.0:${NOMAD_PORT_fleet}",
          "--control-api-address", "0.0.0.0:${NOMAD_PORT_control}"
        ]
      }

      resources {
        cpu = 500
        memory = 256
      }
    }
  }
}
```

## `supernode1.hcl`

```hcl
job "supernode1" {
  datacenters = ["dc1"]
  type        = "service"

  # Only run on nodes marked "node"
  constraint {
    attribute = "${node.class}"
    operator  = "="
    value     = "node"
  }

  group "supernode1" {
    count = 1

    # Allocate dynamic port for ClientAppIO API
    network {
      port "clientappio" {}
    }

    task "supernode1" {
      driver = "docker"

      config {
        image = "flwr/supernode:1.25.0"
        ports = ["clientappio"]

        # Important: Arguments reference env vars inserted below
        args = [
          "--insecure",
          "--superlink", "${SUP_LINK_ADDR}",
          "--clientappio-api-address", "0.0.0.0:${NOMAD_PORT_clientappio}",
          "--isolation", "process",
          "--node-config", "partition-id=0 num-partitions=2"
        ]
      }

      # Inject dynamic SuperLink address from native service discovery
      template {
        data = <<EOF
{{ range nomadService "superlink-fleet" }}
SUP_LINK_ADDR="{{ .Address }}:{{ .Port }}"
{{ end }}
EOF
        destination = "local/env.txt"
        env         = true
      }

      resources {
        cpu    = 500
        memory = 512
      }

      service {
        name     = "supernode1-clientappio"
        port     = "clientappio"
        provider = "nomad"
      }
    }
  }
}
```

## `supernode2.hcl`

```hcl
job "supernode2" {
  datacenters = ["dc1"]
  type        = "service"

  # Only run on nodes marked "node"
  constraint {
    attribute = "${node.class}"
    operator  = "="
    value     = "node"
  }

  group "supernode2" {
    count = 1

    # Allocate dynamic port for ClientAppIO API
    network {
      port "clientappio" {}
    }

    task "supernode2" {
      driver = "docker"

      config {
        image = "flwr/supernode:1.25.0"
        ports = ["clientappio"]

        # Important: Arguments reference env vars inserted below
        args = [
          "--insecure",
          "--superlink", "${SUP_LINK_ADDR}",
          "--clientappio-api-address", "0.0.0.0:${NOMAD_PORT_clientappio}",
          "--isolation", "process",
          "--node-config", "partition-id=1 num-partitions=2"
        ]
      }

      # Inject dynamic SuperLink address from native service discovery
      template {
        data = <<EOF
{{ range nomadService "superlink-fleet" }}
SUP_LINK_ADDR="{{ .Address }}:{{ .Port }}"
{{ end }}
EOF
        destination = "local/env.txt"
        env         = true
      }

      resources {
        cpu    = 500
        memory = 512
      }

      service {
        name     = "supernode2-clientappio"
        port     = "clientappio"
        provider = "nomad"
      }
    }
  }
}
```

## `superexec_serverapp.hcl`

```hcl
job "superexec-serverapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "superexec-serverapp" {
    count = 1

    # MUST run on link node (same host as SuperLink)
    constraint {
      attribute = "${node.class}"
      operator  = "="
      value     = "link"
    }

    task "superexec-serverapp" {
      driver = "docker"
      user = "root"
      config {
        image = "jiahborcn/flwr_superexec:0.0.1"

        entrypoint = ["flower-superexec"]

        args = [
          "--insecure",
          "--plugin-type", "serverapp",
          "--appio-api-address", "${SERVERAPP_IO}",
          "--flwr-dir", "/tmp/.flwr"
        ]
      }

      resources {
        cpu    = 1000
        memory = 1024
      }

      # Create env var SERVERAPP_IO="<ip:port>"
      template {
        data = <<EOF
{{ range nomadService "superlink-serverappio" }}
SERVERAPP_IO="{{ .Address }}:{{ .Port }}"
{{ end }}
EOF
        destination = "local/env.txt"
        env         = true
      }
    }
  }
}
```

## `superexec_clientapp1.hcl`

```hcl
job "superexec-clientapp1" {
  datacenters = ["dc1"]
  type        = "service"

  group "superexec-clientapp1" {
    count = 1

    # Run only on worker nodes
    constraint {
      attribute = "${node.class}"
      operator  = "="
      value     = "node"
    }

    task "superexec-clientapp1" {
      driver = "docker"
      user = "root"
      config {
        image = "jiahborcn/flwr_superexec:0.0.1"

        entrypoint = ["flower-superexec"]

        args = [
          "--insecure",
          "--plugin-type", "clientapp",
          "--appio-api-address", "${CLIENT_IO}",
          "--flwr-dir", "/tmp/.flwr"
        ]
      }

      resources {
        cpu    = 1000
        memory = 1024
      }

      # Inject CLIENT_IO="{{ip:port}}" from service discovery
      template {
        data = <<EOF
{{ range nomadService "supernode1-clientappio" }}
CLIENT_IO="{{ .Address }}:{{ .Port }}"
{{ end }}
EOF
        destination = "local/env.txt"
        env         = true
      }
    }
  }
}
```

## `superexec_clientapp2.hcl`

```hcl
job "superexec-clientapp2" {
  datacenters = ["dc1"]
  type        = "service"

  group "superexec-clientapp2" {
    count = 1

    constraint {
      attribute = "${node.class}"
      operator  = "="
      value     = "node"
    }

    task "superexec-clientapp2" {
      driver = "docker"
      user = "root" 
      config {
        image = "jiahborcn/flwr_superexec:0.0.1"

        entrypoint = ["flower-superexec"]

        args = [
          "--insecure",
          "--plugin-type", "clientapp",
          "--appio-api-address", "${CLIENT_IO}",
          "--flwr-dir", "/tmp/.flwr"
        ]
      }

      resources {
        cpu    = 1000
        memory = 1024
      }

      template {
        data = <<EOF
{{ range nomadService "supernode2-clientappio" }}
CLIENT_IO="{{ .Address }}:{{ .Port }}"
{{ end }}
EOF
        destination = "local/env.txt"
        env         = true
      }
    }
  }
}
```

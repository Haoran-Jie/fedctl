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
        image = "flwr/supernode:1.23.0"
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
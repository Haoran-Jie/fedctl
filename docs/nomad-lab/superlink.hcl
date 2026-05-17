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
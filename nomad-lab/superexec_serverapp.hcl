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
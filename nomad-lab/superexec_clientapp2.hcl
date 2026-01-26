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
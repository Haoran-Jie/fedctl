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
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

        entrypoint = ["/bin/sh", "-lc"]

        args = [
          "PATH=\"/python/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\"; exec flower-superexec --insecure --plugin-type clientapp --appio-api-address \"$${CLIENT_IO}\" --flwr-dir /tmp/.flwr"
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

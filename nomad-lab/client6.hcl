data_dir = "/Users/samueljie/nomad-data/client6"
bind_addr = "0.0.0.0"

advertise {
  http = "127.0.0.1:6156"
  rpc  = "127.0.0.1:6157"
  serf = "127.0.0.1:6158"
}

ports {
  http = 6156
  rpc  = 6157
  serf = 6158
}

client {
  enabled = true
  servers = ["127.0.0.1:4647"]
  node_class = "submit"
  network_interface = "en0"

  meta {
    device_type = "submit"
  }

  host_volume "docker-socket" {
    path      = "/var/run/docker.sock"
    read_only = false
  }

  gc_interval = "10m"
  gc_max_allocs = 200
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

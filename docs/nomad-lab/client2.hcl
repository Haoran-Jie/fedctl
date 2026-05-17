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

  meta {
    device_type = "rpi"
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
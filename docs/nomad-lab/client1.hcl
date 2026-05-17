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


  # Optional (handy for uniform querying, but not required)
  meta {
    device_type = "link"
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
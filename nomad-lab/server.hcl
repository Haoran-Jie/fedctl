data_dir = "/Users/samueljie/nomad-data/server"
bind_addr = "0.0.0.0"

advertise {
  http = "{{ GetInterfaceIP \"en0\" }}:4646"
  rpc  = "{{ GetInterfaceIP \"en0\" }}:4647"
  serf = "{{ GetInterfaceIP \"en0\" }}:4648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

client {
  enabled = false
}

acl {
  enabled = true
}

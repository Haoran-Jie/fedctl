nomad agent -config=server.hcl
nomad agent -config=client1.hcl
nomad agent -config=client2.hcl
nomad agent -config=client3.hcl
nomad job run superlink.hcl
nomad job run supernode1.hcl
nomad job run supernode2.hcl
nomad job run superexec_serverapp.hcl
nomad job run superexec_clientapp1.hcl
nomad job run superexec_clientapp2.hcl

nomad job status superlink # Get the allocation ID of the running superlink job
nomad alloc status 8081a9cc # Replace with actual allocation ID to get the control API address

flwr run quickstart-sklearn-tabular --stream
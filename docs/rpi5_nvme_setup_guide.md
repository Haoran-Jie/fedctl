# Raspberry Pi 5 NVMe Setup Guide for the fedctl Cluster

This guide is for your actual `fedctl` hardware setup, not a single standalone Pi.

The goal is:
- boot each Raspberry Pi 5 from NVMe with no microSD,
- bring it onto the lab LAN with SSH working,
- assign it a stable hostname and IP,
- then let the existing Ansible playbook install Docker, Nomad, and submit-service roles.

This fits the current cluster shape encoded in [ansible/inventories/prod/hosts.ini](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/inventories/prod/hosts.ini) and described in [ansible/README.md](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/README.md).

## Intended Use In This Repo

Your cluster is currently modeled as:
- `rpi1`: Nomad server and submit-service host
- `rpi2`, `rpi5`, `rpi6`: submit nodes
- `rpi3`, `rpi7`, `rpi8`, `rpi9`: superlink nodes
- `rpi4`, `rpi10` to `rpi24`: supernode worker nodes

So this document should be used when:
- provisioning a new Pi from scratch,
- reprovisioning one failed Pi,
- or scaling the cluster out to around 20+ Pis.

The operating model is:
1. Flash Raspberry Pi OS Lite to NVMe.
2. Set hostname, SSH, username, and network access.
3. Physically install the NVMe HAT and boot.
4. Verify SSH access and base health.
5. Add the node to Ansible inventory with the correct role metadata.
6. Run the existing Ansible playbook to configure Nomad and Docker.

## Hardware Per Node

For each Raspberry Pi 5 node:
- Raspberry Pi 5
- NVMe SSD
- NVMe HAT or NVMe-to-USB adapter for flashing
- Ethernet connection
- Power supply or PoE
- Cooling fan/heatsink

For cluster work, Ethernet is the default. Do not rely on Wi-Fi for Nomad cluster nodes.

## Before You Start

Decide these values before flashing:
- hostname, for example `rpi10`
- static IP or DHCP reservation, for example `192.168.8.110`
- node role:
  - `submit`
  - `link`
  - `node`
- device type metadata:
  - `submit`
  - `link`
  - `rpi`
- SSH username

For this repo, the established naming pattern is:
- `rpi1` to `rpi24`
- IP range `192.168.8.101` to `192.168.8.124`

Keep that pattern unless you are deliberately renumbering the cluster.

## 1. Flash Raspberry Pi OS Lite to NVMe

Use Raspberry Pi Imager and flash the NVMe while attached over USB to your laptop.

Recommended settings:
- Device: `Raspberry Pi 5`
- OS: `Raspberry Pi OS Lite (64-bit)`
- Storage: the NVMe drive

Open the advanced settings in Raspberry Pi Imager and set:
- hostname: exact cluster hostname, for example `rpi10`
- enable SSH: yes
- username: the SSH user you want to use on that node
- password: temporary bootstrap password if needed
- locale/timezone: your lab defaults
- Wi-Fi: leave disabled if this is an Ethernet-only cluster node

For this cluster, it is better to use the final hostname immediately instead of flashing every node as `raspberrypi`.

## 2. Assemble the Pi

After flashing:
1. Move the NVMe SSD into the Pi 5 NVMe HAT.
2. Connect the PCIe ribbon correctly.
3. Mount the HAT and cooling.
4. Connect Ethernet.
5. Connect power or PoE.

You want the node physically in its final rack or switch position before assigning it a final IP reservation.

## 3. First Boot and Access

Boot the Pi and connect over SSH.

Typical checks:

```bash
ssh <user>@rpi10.local
```

or, if using the reserved IP:

```bash
ssh <user>@192.168.8.110
```

Once in:

```bash
hostname
hostname -I
lsblk
findmnt /
```

You want to confirm:
- the hostname is correct,
- the node has the expected LAN IP,
- the root filesystem is on the NVMe-backed disk,
- and the machine is reachable over Ethernet.

## 4. Base System Preparation

On first login, do the minimum bootstrap:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl unzip ca-certificates python3 python3-pip python3-venv
```

This roughly matches the baseline package intent now automated by the `base_system` role in [/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/roles/base_system/tasks/main.yml](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/roles/base_system/tasks/main.yml).

If you are going to let Ansible handle everything immediately after first boot, you can keep manual package setup minimal.

## 5. Network Expectations for This Cluster

For the fedctl cluster, every node should be on the same LAN and able to reach:
- `rpi1:4646` for Nomad HTTP API where required
- `rpi1:4647` for Nomad RPC
- `rpi1:4648` for Nomad Serf
- `rpi1:8080` for submit-service where required
- peer nodes for Flower runtime traffic after Nomad schedules jobs

Practically:
- all Nomad clients must reach the Nomad server,
- the Nomad server must reach the clients,
- and scheduled jobs must be able to talk across nodes.

This is why the migration plan in [docs/migration_plan_hardware.md](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/migration_plan_hardware.md) assumes a private east-west cluster LAN.

## 6. Add the Node to Ansible Inventory

Once the OS is up and SSH works, add the node to [ansible/inventories/prod/hosts.ini](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/inventories/prod/hosts.ini).

Examples:

Submit node:

```ini
rpi25 ansible_host=192.168.8.125 ansible_user=rpi25 nomad_node_class=submit nomad_device_type=submit nomad_enable_docker_socket=true
```

SuperLink node:

```ini
rpi25 ansible_host=192.168.8.125 ansible_user=rpi25 nomad_node_class=link nomad_device_type=link
```

Supernode worker:

```ini
rpi25 ansible_host=192.168.8.125 ansible_user=rpi25 nomad_node_class=node nomad_device_type=rpi
```

Use the correct inventory group:
- `nomad_submit_clients`
- `nomad_superlink_clients`
- `nomad_supernode_clients`

Do not put new machines directly into `nomad_servers` unless you are intentionally changing the server quorum design.

## 7. What Ansible Will Do

When you run the playbook, it will configure the node according to its group and host vars.

From [ansible/site.yml](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/site.yml), the sequence is:
1. install baseline packages on all nodes,
2. configure Nomad server role on `nomad_servers`,
3. install Docker on `nomad_clients`,
4. configure Nomad client role on `nomad_clients`,
5. deploy submit-service on `submit_service`.

For a new worker Pi, the important parts are:
- Docker install if it is a Nomad client
- Nomad binary install
- Nomad client config at `/etc/nomad.d/client.hcl`
- `nomad` systemd service enable/start

The current cluster-wide settings come from:
- [ansible/group_vars/all.yml](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/group_vars/all.yml)
- [ansible/group_vars/nomad_clients.yml](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/group_vars/nomad_clients.yml)
- [ansible/group_vars/nomad_servers.yml](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/group_vars/nomad_servers.yml)

Important current values:
- Nomad version: `1.11.1`
- Datacenter: `dc1`
- Nomad server RPC endpoint list currently points at `192.168.8.101:4647`
- Docker insecure registry currently includes `192.168.8.101:5000`

## 8. Run Ansible for the New Node

From repo root:

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible
../.venv/bin/ansible -i inventories/prod/hosts.ini rpi10 -m ping
../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit rpi10
```

If sudo on the node still prompts for a password:

```bash
../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit rpi10 --ask-become-pass
```

If you are provisioning many new Pis, do it in batches by group, not all at once on first rollout.

Examples:

```bash
../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_submit_clients
../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_superlink_clients
../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_supernode_clients
```

## 9. Verify Node Joined the Cluster

After Ansible finishes, verify from `rpi1` or from any machine that can reach Nomad:

```bash
nomad node status
```

You should see the new node in the correct class.

If you want to inspect one node:

```bash
nomad node status <node-id>
```

At minimum verify:
- node is `ready`
- node class is correct
- metadata `device_type` is correct
- Docker-based allocations can run on it if expected

## 10. Suggested Per-Node Bring-Up Checklist

For each new Pi:
1. Flash NVMe with final hostname and SSH enabled.
2. Boot on Ethernet.
3. Verify SSH and IP.
4. Add DHCP reservation if needed.
5. Add the node to Ansible inventory with the right role vars.
6. Run `ansible -m ping`.
7. Run `ansible-playbook --limit <host>`.
8. Verify it appears in `nomad node status`.

This is the repeatable path if you are bringing up around 20 Pis.

## 11. Cluster-Specific Notes

- Do not manually hand-install Nomad on each node unless Ansible is failing and you are debugging. The repo already codifies the desired state.
- Keep hostnames, IPs, and inventory aligned. Most cluster confusion comes from those drifting apart.
- For submit nodes, `nomad_enable_docker_socket=true` matters because the submit runner mounts `/var/run/docker.sock`.
- For supernode workers, `nomad_device_type=rpi` matters because placement logic uses this metadata.
- If you expand beyond one server, you will also need to change the Nomad server quorum settings and `nomad_server_rpc_endpoints`.

## 12. What This Guide Does Not Cover

This guide stops at node provisioning and cluster join. It does not cover:
- replacing the single Nomad server with a 3-server quorum,
- registry TLS hardening,
- AWS credential setup for submit-service presign,
- or Jetson-specific boot/storage differences.

Those belong in the broader migration and operations docs, especially [docs/migration_plan_hardware.md](/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/migration_plan_hardware.md).

# Campus Ethernet Reconfiguration Reference

Use this when a Raspberry Pi needs its campus Ethernet static IPv4 profile reapplied.

## Existing Ansible path

The repo already contains a dedicated playbook:

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/campus_ethernet.yml`

It configures the `eth0` NetworkManager connection named `netplan-eth0` using the host-to-IP map in:

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/vars/campus_ethernet.yml`

## Campus Ethernet settings

The current campus settings in the repo are:

- interface: `eth0`
- connection: `netplan-eth0`
- prefix: `/22`
- netmask: `255.255.252.0`
- gateway: `128.232.60.1`
- DNS: `128.232.1.1`, `128.232.1.2`

For `rpi5-014`, the mapped campus IP is:

- `128.232.61.101`

## One-host recovery when the node is not in the main inventory

If the host is reachable only on its cluster-side address and is currently commented out in `inventories/prod/hosts.ini`, use a temporary inventory file so the inventory hostname still matches the static-IP map key.

From the repo root:

```bash
printf '[targets]\nrpi5-014 ansible_host=192.168.8.126 ansible_user=rpi ansible_ssh_common_args="-o ProxyJump=rpi@100.108.13.23"\n' > /tmp/rpi5-014.ini

cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i /tmp/rpi5-014.ini campus_ethernet.yml --limit rpi5-014
```

Note: the important detail is that the inventory hostname is `rpi5-014`; that is how the playbook looks up `128.232.61.101` from `vars/campus_ethernet.yml`.

## If the host is already back in the main inventory

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini campus_ethernet.yml --limit rpi5-014
```

## Verification

Check the host after the playbook completes:

```bash
ssh -J rpi@100.108.13.23 rpi@128.232.61.101 'hostname; ip -4 -br addr show eth0; ip route | head -n 5'
```

Expected Ethernet address:

- `128.232.61.101/22` on `eth0`

Expected route details:

- default route via `128.232.60.1`
- DNS servers `128.232.1.1` and `128.232.1.2`

## Current note for rpi5-014

A recovery attempt from this workspace found that `rpi5-014` was not currently reachable on either:

- cluster-side address `192.168.8.126` via `ProxyJump` through `rpi@100.108.13.23`
- campus-side address `128.232.61.101`

So the Ansible command above is the correct recovery mechanism, but it still requires the host to be reachable over at least one network path first.

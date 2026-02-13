# Ansible Cluster Automation for fedctl

This directory automates your hardware deployment so you can scale from 4 RPis to 24 RPis without manual SSH per node.

## Topology encoded in inventory

`inventories/prod/hosts.ini` currently models:
- `1` Nomad server + submit service (`rpi1`)
- `3` submit clients (`rpi2`, `rpi5`, `rpi6`)
- `4` superlink clients (`rpi3`, `rpi7`, `rpi8`, `rpi9`)
- `16` supernode clients (`rpi4`, `rpi10`-`rpi24`)

If your IPs differ, edit `ansible_host` values.

## What this playbook manages

- Base packages on all nodes.
- Nomad install/config/service on servers and clients.
- Docker install + insecure registry merge on all Nomad clients.
- Submit service deploy (git checkout, venv deps, env file, systemd service) on `submit_service` hosts.

## Prerequisites

1. Control machine has Ansible:
```bash
python3 -m pip install --user ansible
```
2. SSH access to all RPis works with your key.
3. If host usernames are not in SSH config, add `ansible_user=<user>` in inventory per host.

## First run

From repo root:
```bash
cd ansible
ansible -i inventories/prod/hosts.ini all -m ping
ansible-playbook -i inventories/prod/hosts.ini site.yml --ask-become-pass
```

If your sudo does not require a password, omit `--ask-become-pass`.

## Safe rollout strategy

Run in slices first:
```bash
ansible-playbook -i inventories/prod/hosts.ini site.yml --limit rpi1 --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_submit_clients --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_superlink_clients --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini site.yml --limit nomad_supernode_clients --ask-become-pass
```

## Scaling later

To add more RPis, only update inventory groups with new hosts and rerun:
```bash
ansible-playbook -i inventories/prod/hosts.ini site.yml --ask-become-pass
```

No playbook changes are needed for role-balanced scaling.

## Variables you should edit

- `group_vars/all.yml`
  - `nomad_server_rpc_endpoints`
  - `docker_insecure_registries`
- `group_vars/submit_service.yml`
  - `submit_repo_url`, `submit_repo_version`
  - `submit_tokens` (prefer Ansible Vault)
  - `submit_allow_unauth`

## Optional hardening

- Move `submit_tokens` into `group_vars/submit_service.vault.yml` encrypted with `ansible-vault`.
- Replace insecure registry with TLS registry and remove `docker_insecure_registries`.
- Expand Nomad to 3 servers and set `nomad_server_bootstrap_expect: 3`.

# Ansible Cluster Automation for fedctl

This directory automates your hardware deployment so you can scale from 4 RPis to 24 RPis without manual SSH per node.

## Topology encoded in inventory

`inventories/prod/hosts.ini` currently models:
- `1` Nomad server + submit service + registry (`rpi5-001`)
- `1` submit client (`rpi5-002`)
- `1` superlink client (`rpi5-003`)
- `1` supernode client (`rpi5-004`)
- additional commented `rpi5-005` to `rpi5-024` entries for later scale-out

If your IPs differ, edit `ansible_host` values.

## What this playbook manages

- Base packages on all nodes.
- Hostname normalization and time sync on all nodes.
- Nomad install/config/service on servers and clients.
- Docker install + insecure registry merge on all Nomad clients and registry hosts.
- Local Docker registry deploy on `registry_hosts`.
- Optional Tailscale install/join on `tailscale_nodes`.
- Submit service deploy (git checkout, venv deps, env file, systemd service) on `submit_service` hosts.
- Final readiness validation for Nomad, registry, and submit service.

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
ansible-playbook -i inventories/prod/hosts.ini site.yml --limit rpi5-001 --ask-become-pass
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
- `group_vars/tailscale_nodes.yml`
  - `tailscale_enabled`
  - `tailscale_auth_key` (recommended via `TAILSCALE_AUTH_KEY` env var)
  - `tailscale_enable_ssh`
- `group_vars/submit_service.yml`
  - `submit_repo_url`, `submit_repo_version`
  - `submit_tokens` (prefer Ansible Vault)
  - `submit_allow_unauth`
  - `submit_aws_shared_credentials_file`, `submit_aws_config_file`
  - `submit_aws_credentials_src`, `submit_aws_config_src`

## Optional hardening

- Move `submit_tokens` into `group_vars/submit_service.vault.yml` encrypted with `ansible-vault`.
- Do not store `tailscale_auth_key` in plain text. The current setup reads it from the control-machine environment:
  - `export TAILSCALE_AUTH_KEY=tskey-auth-...`
  - `ansible-playbook -i inventories/prod/hosts.ini site.yml`
- Submit-service can copy AWS config directly from the Ansible control machine using:
  - `submit_aws_credentials_src`
  - `submit_aws_config_src`
- The current `group_vars/submit_service.yml` points these at:
  - `{{ lookup('env', 'HOME') }}/.aws/credentials`
  - `{{ lookup('env', 'HOME') }}/.aws/config`
- Replace insecure registry with TLS registry and remove `docker_insecure_registries`.
- Expand Nomad to 3 servers and set `nomad_server_bootstrap_expect: 3`.

## Image seeding after registry recovery

If `rpi5-001` is freshly reflashed, the local registry comes back empty even though the registry service is recreated. Seed the submit runner image from the control machine with:

```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini seed_images.yml
```

This playbook:
- checks whether the local registry already has `fedctl-submit:latest`
- builds from `templates/submit/Dockerfile.submit-runner` on the control machine only if missing
- pushes the image to the local registry

To force a rebuild:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini seed_images.yml -e submit_runner_image_seed_force=true
```

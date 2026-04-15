# Ansible Cluster Automation for fedctl

This directory automates your hardware deployment so you can scale from a small test set to the current cluster without manual SSH per node.

## Topology encoded in inventory

`inventories/prod/hosts.ini` currently models:
- `1` Nomad server + submit service + registry (`rpi5-005`)
- `2` submit clients (`rpi5-006` to `rpi5-007`)
- `3` superlink clients (`rpi5-008` to `rpi5-010`)
- `14` rpi5 supernode clients (`rpi5-011` to `rpi5-024`)
- `10` rpi4 supernode clients (`rpi4-001` to `rpi4-010`)

If your IPs differ, edit inventory host vars.

- `ansible_host`: how Ansible/SSH reaches the node
- `tailscale_ip`: out-of-band fallback address for recovery access
- `cluster_node_ip`: the cluster LAN IP that Nomad and the local registry should advertise/use

The current inventory uses the campus Ethernet IP as `ansible_host` and retains the Tailscale address separately as `tailscale_ip`.

## What these playbooks manage

- Base packages on all nodes.
- Hostname normalization and time sync on all nodes.
- Nomad install/config/service on servers and clients.
- Docker install + insecure registry merge on all Nomad clients and registry hosts.
- Local Docker registry deploy on `registry_hosts`.
- Local registry tag retention on `registry_hosts` for `*-superexec` repositories.
- Optional Tailscale install/join on `tailscale_nodes`.
- Submit service deploy (git checkout, venv deps, env file, systemd service) on `submit_service` hosts.
- Scheduled Docker cleanup on submit nodes only.
- Final readiness validation for Nomad, registry, submit service, and Tailscale.

## Playbook layout

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/site.yml`
  - orchestration entrypoint for a full cluster rollout
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/playbooks/submit_service.yml`
  - submit-service only
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/playbooks/validate.yml`
  - validation only
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/playbooks/submit_client_cleanup.yml`
  - submit-node Docker cleanup only
- other files under `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/ansible/playbooks/`
  - focused deploy slices by concern

This avoids using `site.yml --limit <group>` for targeted maintenance on hosts that belong to multiple groups.

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

Run targeted playbooks instead of limiting the monolithic site playbook:
```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/submit_service.yml --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini playbooks/validate.yml --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini playbooks/nomad_server.yml --ask-become-pass
ansible-playbook -i inventories/prod/hosts.ini playbooks/nomad_client.yml --ask-become-pass
```

## Scaling later

To add more RPis, only update inventory groups with new hosts and rerun:
```bash
ansible-playbook -i inventories/prod/hosts.ini site.yml --ask-become-pass
```

No playbook changes are needed for role-balanced scaling.

## Common targeted operations

Submit service only:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini playbooks/submit_service.yml
```

Validation only:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini playbooks/validate.yml
```

Registry only:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini playbooks/registry.yml
```

Nomad clients only:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini playbooks/nomad_client.yml
```

Submit-node Docker cleanup only:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini playbooks/submit_client_cleanup.yml
```

## Variables you should edit

- `group_vars/all.yml`
  - `nomad_server_rpc_endpoints`
  - `docker_insecure_registries`
  - `registry_retention_keep_tags`
  - `registry_retention_repo_patterns`
  - `registry_retention_schedule`
  - `registry_retention_dry_run`
- `group_vars/tailscale_nodes.yml`
  - `tailscale_enabled`
  - `tailscale_auth_key`
  - `tailscale_enable_ssh`
- `group_vars/nomad_clients.yml`
  - `docker_image_cleanup_enabled`
  - `docker_image_cleanup_node_classes`
  - `docker_image_cleanup_until`
  - `docker_image_cleanup_schedule`
- Optional local-only file:
  - `group_vars/tailscale_nodes.local.yml`
  - git-ignored
  - loaded automatically by `site.yml`
  - recommended place for `tailscale_auth_key`
- `group_vars/submit_service.yml`
  - `submit_repo_url`, `submit_repo_version`
  - `submit_tokens` (prefer Ansible Vault)
  - `submit_allow_unauth`
  - `submit_aws_shared_credentials_file`, `submit_aws_config_file`
  - `submit_aws_credentials_src`, `submit_aws_config_src`

## Optional hardening

- Move `submit_tokens` into `group_vars/submit_service.vault.yml` encrypted with `ansible-vault`.
- Do not store `tailscale_auth_key` in tracked files. Recommended local-only file:
  - `ansible/group_vars/tailscale_nodes.local.yml`
  - `tailscale_auth_key: "tskey-auth-..."`
- Submit-service can copy AWS config directly from the Ansible control machine using:
  - `submit_aws_credentials_src`
  - `submit_aws_config_src`
- The current `group_vars/submit_service.yml` points these at:
  - `{{ lookup('env', 'HOME') }}/.aws/credentials`
  - `{{ lookup('env', 'HOME') }}/.aws/config`
- Replace insecure registry with TLS registry and remove `docker_insecure_registries`.
- Expand Nomad to 3 servers and set `nomad_server_bootstrap_expect: 3`.

## Image seeding after registry recovery

If `rpi5-005` is freshly reflashed, the local registry comes back empty even though the registry service is recreated. Seed the submit runner image from the control machine with:

```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini seed_images.yml
```

This playbook:
- checks whether the local registry already has `fedctl-submit:latest`
- checks out the fedctl repository on the registry host
- builds from `templates/submit/Dockerfile.submit-runner` on the registry host only if missing
- pushes the image to the local registry

To force a rebuild:
```bash
cd ansible
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible-cp ../.venv/bin/ansible-playbook -i inventories/prod/hosts.ini seed_images.yml -e submit_runner_image_seed_force=true
```

## Automated image cleanup

The current automation intentionally separates two concerns:

- Registry-side retention on `registry_hosts`
  - enables the registry delete API
  - deletes old `*-superexec` tags by policy
  - keeps `latest` plus the 10 newest tags per matching repository
- Node-side Docker cleanup on submit nodes
  - prunes stopped containers older than 24h
  - prunes unused images older than 24h

Default schedules:

- registry retention: daily at `03:30`
- submit-node Docker cleanup: daily at `04:00`

Important limitation:

- This does **not** run `registry garbage-collect`.
- Old blobs may remain under `/opt/registry/data` until a future offline maintenance window is introduced.

Dry-run the registry retention policy on the registry host:
```bash
ssh rpi@128.232.61.111 'sudo FEDCTL_DRY_RUN=true /usr/bin/env python3 /usr/local/bin/fedctl-registry-retention.py'
```

Run the registry retention service immediately:
```bash
ssh rpi@128.232.61.111 'sudo systemctl start fedctl-registry-retention.service'
```

Run the submit-node Docker cleanup service immediately on a submit node:
```bash
ssh rpi@128.232.61.93 'sudo systemctl start fedctl-docker-image-cleanup.service'
```

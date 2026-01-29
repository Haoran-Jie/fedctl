from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader

from . import naming
from .network import NetworkPlan, assignment_key
from .spec import DeploySpec
from .plan import SupernodePlacement


@dataclass(frozen=True)
class RenderedJobs:
    superlink: dict[str, Any]
    supernodes: dict[str, Any]
    superexec_serverapp: dict[str, Any]
    superexec_clientapps: list[dict[str, Any]]


def render_deploy(spec: DeploySpec) -> RenderedJobs:
    env = _template_env()

    superlink_context = _superlink_context(spec)
    superlink = _render_template(env, "superlink.json.j2", superlink_context)

    supernodes_context = _supernodes_context(spec)
    supernodes = _render_template(env, "supernodes.json.j2", supernodes_context)

    superexec_serverapp_context = _superexec_serverapp_context(spec)
    superexec_serverapp = _render_template(
        env, "superexec_serverapp.json.j2", superexec_serverapp_context
    )

    superexec_clientapps: list[dict[str, Any]] = []
    for placement in _supernode_placements(spec):
        context = _superexec_clientapp_context(spec, placement)
        superexec_clientapps.append(
            _render_template(env, "superexec_clientapp.json.j2", context)
        )

    _validate_jobs(
        superlink=superlink,
        supernodes=supernodes,
        superexec_serverapp=superexec_serverapp,
        superexec_clientapps=superexec_clientapps,
        spec=spec,
    )

    return RenderedJobs(
        superlink=superlink,
        supernodes=supernodes,
        superexec_serverapp=superexec_serverapp,
        superexec_clientapps=superexec_clientapps,
    )


def _template_env() -> Environment:
    template_root = Path(__file__).resolve().parents[3] / "templates" / "nomad"
    return Environment(loader=FileSystemLoader(str(template_root)), autoescape=False)


def _render_template(env: Environment, name: str, context: dict[str, Any]) -> dict[str, Any]:
    rendered = env.get_template(name).render(**context)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Template {name} rendered invalid JSON: {exc}") from exc


def _superlink_context(spec: DeploySpec) -> dict[str, Any]:
    args = [
        "--insecure",
        "--isolation",
        "process",
        "--serverappio-api-address",
        "0.0.0.0:${NOMAD_PORT_serverappio}",
        "--fleet-api-address",
        "0.0.0.0:${NOMAD_PORT_fleet}",
        "--control-api-address",
        "0.0.0.0:${NOMAD_PORT_control}",
    ]
    if not spec.insecure:
        args = [arg for arg in args if arg != "--insecure"]

    return {
        "job_name": naming.job_superlink(spec.experiment),
        "datacenters": [spec.datacenter],
        "namespace": spec.namespace,
        "node_class": spec.superlink.node_class,
        "image": f"flwr/superlink:{spec.flwr_version}",
        "ports": ["serverappio", "fleet", "control"],
        "services": [
            {
                "Name": naming.service_superlink_serverappio(spec.experiment),
                "PortLabel": "serverappio",
                "Provider": "nomad",
            },
            {
                "Name": naming.service_superlink_fleet(spec.experiment),
                "PortLabel": "fleet",
                "Provider": "nomad",
            },
            {
                "Name": naming.service_superlink_control(spec.experiment),
                "PortLabel": "control",
                "Provider": "nomad",
            },
        ],
        "args": args,
        "cpu": spec.superlink.cpu,
        "memory_mb": spec.superlink.memory_mb,
    }


def _supernodes_context(spec: DeploySpec) -> dict[str, Any]:
    placements = _supernode_placements(spec)
    total_instances = len(placements)
    task_groups = []
    for idx, placement in enumerate(placements, start=1):
        device_type = placement.device_type
        group_suffix = f"{device_type}-{placement.instance_idx}" if device_type else str(idx)
        group_name = f"supernode-{group_suffix}"
        task_name = group_name
        service_name = naming.service_supernode_clientappio(
            spec.experiment, placement.instance_idx, device_type
        )
        template_data = _nomad_service_env(
            naming.service_superlink_fleet(spec.experiment),
            "SUP_LINK_ADDR",
        )
        args = [
            "--insecure",
            "--superlink",
            "${SUP_LINK_ADDR}",
            "--clientappio-api-address",
            "0.0.0.0:${NOMAD_PORT_clientappio}",
            "--isolation",
            "process",
            "--node-config",
            f"partition-id={idx - 1} num-partitions={max(total_instances, 1)}",
        ]
        if not spec.insecure:
            args = [arg for arg in args if arg != "--insecure"]

        constraints = [
            {
                "LTarget": "${node.class}",
                "Operand": "=",
                "RTarget": spec.supernodes.node_class,
            }
        ]
        if device_type:
            constraints.append(
                {
                    "LTarget": "${node.meta.device_type}",
                    "Operand": "=",
                    "RTarget": device_type,
                }
            )
        if placement.node_id:
            constraints.append(
                {
                    "LTarget": "${node.unique.id}",
                    "Operand": "=",
                    "RTarget": placement.node_id,
                }
            )

        cpu, mem = _supernode_resources(spec, device_type)
        tasks = []
        netem_env: dict[str, str] | None = None
        entrypoint = None
        task_args = args
        network_plan = spec.supernodes.network
        cap_add = None
        user = None
        if network_plan is not None:
            profile_name = _network_profile_for(network_plan, placement)
            profile_data = network_plan.profiles.get(profile_name, {})
            if profile_name != "none" and profile_data:
                netem_env = _netem_env(profile_name, profile_data)
                entrypoint = ["/bin/sh", "-lc"]
                task_args = [_netem_wrapper_script(["flower-supernode", *args])]
                cap_add = ["NET_ADMIN"]
                user = "root"
        tasks.append(
            {
                "Name": task_name,
                "Driver": "docker",
                **({"User": user} if user else {}),
                "Config": {
                    "image": spec.supernodes.image or f"flwr/supernode:{spec.flwr_version}",
                    "ports": ["clientappio"],
                    "args": task_args,
                    **({"entrypoint": entrypoint} if entrypoint else {}),
                    **({"cap_add": cap_add} if cap_add else {}),
                },
                **({"Env": netem_env} if netem_env else {}),
                "Templates": [
                    {
                        "EmbeddedTmpl": template_data,
                        "DestPath": "local/env.txt",
                        "Envvars": True,
                    }
                ],
                "Resources": {
                    "CPU": cpu,
                    "MemoryMB": mem,
                },
                "Services": [
                    {
                        "Name": service_name,
                        "PortLabel": "clientappio",
                        "Provider": "nomad",
                    }
                ],
            }
        )
        task_groups.append(
            {
                "Name": group_name,
                "Count": 1,
                "Constraints": constraints,
                "Networks": [{"DynamicPorts": [{"Label": "clientappio"}]}],
                "Tasks": tasks,
            }
        )

    return {
        "job_name": naming.job_supernodes(spec.experiment),
        "datacenters": [spec.datacenter],
        "namespace": spec.namespace,
        "node_class": spec.supernodes.node_class,
        "task_groups": task_groups,
    }


def _netem_task(spec: DeploySpec, placement: SupernodePlacement) -> dict[str, Any] | None:
    network_plan = spec.supernodes.network
    netem_image = spec.supernodes.netem_image
    if network_plan is None or not netem_image:
        return None
    profile_name = _network_profile_for(network_plan, placement)
    profile_data = network_plan.profiles.get(profile_name, {})
    return _netem_task_for_profile(profile_name, profile_data, netem_image)


def _netem_task_for_profile(
    profile_name: str, profile_data: dict[str, float | int], netem_image: str
) -> dict[str, Any] | None:
    if profile_name == "none" or not profile_data:
        return None
    env = _netem_env(profile_name, profile_data)
    return {
        "Name": "netem",
        "Driver": "docker",
        "Lifecycle": {"Hook": "prestart", "Sidecar": True},
        "User": "root",
        "Config": {
            "image": netem_image,
            "command": "/bin/sh",
            "args": ["-c", _netem_script()],
            "cap_add": ["NET_ADMIN"],
        },
        "Env": env,
        "Resources": {
            "CPU": 50,
            "MemoryMB": 64,
        },
    }


def _netem_env(
    profile_name: str, profile_data: dict[str, float | int]
) -> dict[str, str]:
    env = {
        "NET_PROFILE": profile_name,
        "NET_IFACE": "eth0",
    }
    for key, env_key in (
        ("delay_ms", "NET_DELAY_MS"),
        ("jitter_ms", "NET_JITTER_MS"),
        ("loss_pct", "NET_LOSS_PCT"),
        ("rate_mbit", "NET_RATE_MBIT"),
        ("rate_latency_ms", "NET_RATE_LATENCY_MS"),
        ("rate_burst_kbit", "NET_RATE_BURST_KBIT"),
    ):
        value = profile_data.get(key)
        if isinstance(value, (int, float)):
            env[env_key] = str(value)
    return env


def _netem_script() -> str:
    lines = [
        "set -eu",
        'IFACE=\"$${NET_IFACE:-eth0}\"',
        'PROFILE=\"$${NET_PROFILE:-none}\"',
        "tc qdisc del dev \"$IFACE\" root 2>/dev/null || true",
        "if [ \"$PROFILE\" = \"none\" ]; then",
        "  echo \"netem disabled\"",
        "else",
        '  DELAY=\"$${NET_DELAY_MS:-0}\"',
        '  JITTER=\"$${NET_JITTER_MS:-0}\"',
        '  LOSS=\"$${NET_LOSS_PCT:-0}\"',
        '  RATE=\"$${NET_RATE_MBIT:-}\"',
        '  RATE_LATENCY=\"$${NET_RATE_LATENCY_MS:-400}\"',
        '  RATE_BURST=\"$${NET_RATE_BURST_KBIT:-32}\"',
        "  if [ -n \"$RATE\" ]; then",
        "    tc qdisc add dev \"$IFACE\" root handle 1: tbf rate \"$${RATE}mbit\" burst \"$${RATE_BURST}kbit\" latency \"$${RATE_LATENCY}ms\"",
        "    tc qdisc add dev \"$IFACE\" parent 1:1 handle 10: netem delay \"$${DELAY}ms\" \"$${JITTER}ms\" loss \"$${LOSS}%\"",
        "  else",
        "    tc qdisc add dev \"$IFACE\" root netem delay \"$${DELAY}ms\" \"$${JITTER}ms\" loss \"$${LOSS}%\"",
        "  fi",
        "fi",
        "tc qdisc show dev \"$IFACE\" || true",
        "trap 'tc qdisc del dev \"$IFACE\" root 2>/dev/null || true' TERM INT",
        "sleep 3600",
    ]
    return "\n".join(lines)


def _netem_wrapper_script(command: list[str]) -> str:
    cmd = " ".join(shlex.quote(arg) for arg in command)
    lines = [
        "set -eu",
        'PATH="/python/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
        'IFACE="$${NET_IFACE:-eth0}"',
        'PROFILE="$${NET_PROFILE:-none}"',
        "tc qdisc del dev \"$IFACE\" root 2>/dev/null || true",
        "if [ \"$PROFILE\" = \"none\" ]; then",
        "  echo \"netem disabled\"",
        "else",
        '  DELAY="$${NET_DELAY_MS:-0}"',
        '  JITTER="$${NET_JITTER_MS:-0}"',
        '  LOSS="$${NET_LOSS_PCT:-0}"',
        '  RATE="$${NET_RATE_MBIT:-}"',
        '  RATE_LATENCY="$${NET_RATE_LATENCY_MS:-400}"',
        '  RATE_BURST="$${NET_RATE_BURST_KBIT:-32}"',
        "  if [ -n \"$RATE\" ]; then",
        "    tc qdisc add dev \"$IFACE\" root handle 1: tbf rate \"$${RATE}mbit\" burst \"$${RATE_BURST}kbit\" latency \"$${RATE_LATENCY}ms\"",
        "    tc qdisc add dev \"$IFACE\" parent 1:1 handle 10: netem delay \"$${DELAY}ms\" \"$${JITTER}ms\" loss \"$${LOSS}%\"",
        "  else",
        "    tc qdisc add dev \"$IFACE\" root netem delay \"$${DELAY}ms\" \"$${JITTER}ms\" loss \"$${LOSS}%\"",
        "  fi",
        "fi",
        "tc qdisc show dev \"$IFACE\" || true",
        f"exec {cmd}",
    ]
    return "\n".join(lines)


def _network_profile_for(network_plan: NetworkPlan, placement: SupernodePlacement) -> str:
    device_type = placement.device_type if isinstance(placement.device_type, str) else None
    key = assignment_key(device_type)
    assignments = network_plan.assignments.get(key)
    if not assignments:
        return network_plan.default_profile
    if not isinstance(placement.instance_idx, int):
        return network_plan.default_profile
    if placement.instance_idx < 1 or placement.instance_idx > len(assignments):
        return network_plan.default_profile
    return assignments[placement.instance_idx - 1]


def _superexec_serverapp_context(spec: DeploySpec) -> dict[str, Any]:
    args = [
        "--insecure",
        "--plugin-type",
        "serverapp",
        "--appio-api-address",
        "${SERVERAPP_IO}",
        "--flwr-dir",
        spec.superexec.flwr_dir,
    ]
    if not spec.insecure:
        args = [arg for arg in args if arg != "--insecure"]

    entrypoint = ["flower-superexec"]
    env: dict[str, str] = {}
    user = spec.superexec.user
    network_plan = spec.supernodes.network
    if network_plan is not None:
        profile_name = network_plan.default_profile
        profile_data = network_plan.profiles.get(profile_name, {})
        if profile_name != "none" and profile_data:
            entrypoint = ["/bin/sh", "-lc"]
            args = [_netem_wrapper_script(["flower-superexec", *args])]
            env.update(_netem_env(profile_name, profile_data))
            user = "root"
            cap_add = ["NET_ADMIN"]
        else:
            cap_add = None
    else:
        cap_add = None

    return {
        "job_name": naming.job_superexec_serverapp(spec.experiment),
        "datacenters": [spec.datacenter],
        "namespace": spec.namespace,
        "node_class": spec.superexec.node_class_link,
        "image": spec.superexec.image,
        "entrypoint": entrypoint,
        "args": args,
        "template_data": _nomad_service_env(
            naming.service_superlink_serverappio(spec.experiment), "SERVERAPP_IO"
        ),
        "cpu": spec.superexec.cpu,
        "memory_mb": spec.superexec.memory_mb,
        "user": user,
        "env": env,
        "cap_add": cap_add,
    }


def _superexec_clientapp_context(
    spec: DeploySpec, placement: SupernodePlacement
) -> dict[str, Any]:
    args = [
        "--insecure",
        "--plugin-type",
        "clientapp",
        "--appio-api-address",
        "${CLIENT_IO}",
        "--flwr-dir",
        spec.superexec.flwr_dir,
    ]
    if not spec.insecure:
        args = [arg for arg in args if arg != "--insecure"]

    entrypoint = ["flower-superexec"]
    env: dict[str, str] = {}
    user = spec.superexec.user
    network_plan = spec.supernodes.network
    if network_plan is not None:
        profile_name = _network_profile_for(network_plan, placement)
        profile_data = network_plan.profiles.get(profile_name, {})
        if profile_name != "none" and profile_data:
            entrypoint = ["/bin/sh", "-lc"]
            args = [_netem_wrapper_script(["flower-superexec", *args])]
            env.update(_netem_env(profile_name, profile_data))
            user = "root"
            cap_add = ["NET_ADMIN"]
        else:
            cap_add = None
    else:
        cap_add = None

    return {
        "job_name": naming.job_superexec_clientapp(
            spec.experiment,
            placement.instance_idx,
            placement.device_type,
        ),
        "datacenters": [spec.datacenter],
        "namespace": spec.namespace,
        "node_class": spec.superexec.node_class_node,
        "image": spec.superexec.image,
        "entrypoint": entrypoint,
        "args": args,
        "template_data": _nomad_service_env(
            naming.service_supernode_clientappio(
                spec.experiment,
                placement.instance_idx,
                placement.device_type,
            ),
            "CLIENT_IO",
        ),
        "cpu": spec.superexec.cpu,
        "memory_mb": spec.superexec.memory_mb,
        "user": user,
        "env": env,
        "cap_add": cap_add,
    }


def _nomad_service_env(service_name: str, var_name: str) -> str:
    return (
        f'{{{{ range nomadService "{service_name}" }}}}\n'
        f'{var_name}="{{{{ .Address }}}}:{{{{ .Port }}}}"\n'
        "{{ end }}\n"
    )


def _validate_jobs(
    *,
    superlink: dict[str, Any],
    supernodes: dict[str, Any],
    superexec_serverapp: dict[str, Any],
    superexec_clientapps: Iterable[dict[str, Any]],
    spec: DeploySpec,
) -> None:
    if not _has_node_class_constraint(superlink["Job"], spec.superlink.node_class):
        raise ValueError("superlink job missing node.class constraint.")
    if not _has_node_class_constraint(supernodes["Job"], spec.supernodes.node_class):
        raise ValueError("supernodes job missing node.class constraint.")

    if not _group_constraint(superexec_serverapp["Job"], spec.superexec.node_class_link):
        raise ValueError("superexec-serverapp missing node.class constraint.")
    for job in superexec_clientapps:
        if not _group_constraint(job["Job"], spec.superexec.node_class_node):
            raise ValueError("superexec-clientapp missing node.class constraint.")

    superlink_services = _collect_service_names(superlink["Job"])
    supernodes_services = _collect_service_names(supernodes["Job"])

    required_superlink = {
        naming.service_superlink_fleet(spec.experiment),
        naming.service_superlink_serverappio(spec.experiment),
    }
    if not required_superlink.issubset(superlink_services):
        missing = required_superlink - superlink_services
        raise ValueError(f"superlink missing services: {sorted(missing)}")

    for placement in _supernode_placements(spec):
        name = naming.service_supernode_clientappio(
            spec.experiment, placement.instance_idx, placement.device_type
        )
        if name not in supernodes_services:
            raise ValueError(f"supernodes missing service: {name}")


def _supernode_placements(spec: DeploySpec) -> list[SupernodePlacement]:
    if spec.supernodes.placements:
        return spec.supernodes.placements
    placements: list[SupernodePlacement] = []
    if spec.supernodes.by_type:
        for device_type, count in spec.supernodes.by_type.items():
            for idx in range(1, count + 1):
                placements.append(
                    SupernodePlacement(
                        device_type=device_type,
                        instance_idx=idx,
                        node_id=None,
                    )
                )
        return placements
    for idx in range(1, spec.supernodes.count + 1):
        placements.append(
            SupernodePlacement(device_type=None, instance_idx=idx, node_id=None)
        )
    return placements


def _supernode_resources(spec: DeploySpec, device_type: str | None) -> tuple[int, int]:
    default_cpu = spec.supernodes.cpu
    default_mem = spec.supernodes.memory_mb
    if spec.supernodes.default_resources:
        default_cpu = int(spec.supernodes.default_resources.get("cpu", default_cpu))
        default_mem = int(spec.supernodes.default_resources.get("mem", default_mem))

    if device_type and spec.supernodes.resources_by_type:
        entry = spec.supernodes.resources_by_type.get(device_type)
        if isinstance(entry, dict):
            cpu = int(entry.get("cpu", default_cpu))
            mem = int(entry.get("mem", default_mem))
            return cpu, mem
    return default_cpu, default_mem

    _validate_ports(superlink["Job"])
    _validate_ports(supernodes["Job"])
    _validate_ports(superexec_serverapp["Job"])
    for job in superexec_clientapps:
        _validate_ports(job["Job"])


def _collect_service_names(job: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for group in job.get("TaskGroups", []):
        for svc in group.get("Services", []):
            if isinstance(svc, dict) and isinstance(svc.get("Name"), str):
                names.add(svc["Name"])
        for task in group.get("Tasks", []):
            for svc in task.get("Services", []):
                if isinstance(svc, dict) and isinstance(svc.get("Name"), str):
                    names.add(svc["Name"])
    return names


def _has_node_class_constraint(job: dict[str, Any], expected: str) -> bool:
    for constraint in job.get("Constraints", []):
        if (
            constraint.get("LTarget") == "${node.class}"
            and constraint.get("Operand") == "="
            and constraint.get("RTarget") == expected
        ):
            return True
    return False


def _group_constraint(job: dict[str, Any], expected: str) -> bool:
    for group in job.get("TaskGroups", []):
        for constraint in group.get("Constraints", []):
            if (
                constraint.get("LTarget") == "${node.class}"
                and constraint.get("Operand") == "="
                and constraint.get("RTarget") == expected
            ):
                return True
    return False


def _validate_ports(job: dict[str, Any]) -> None:
    for group in job.get("TaskGroups", []):
        labels = set()
        for network in group.get("Networks", []):
            for port in network.get("DynamicPorts", []):
                label = port.get("Label")
                if isinstance(label, str):
                    labels.add(label)
        for task in group.get("Tasks", []):
            config = task.get("Config", {})
            ports = config.get("ports", [])
            if not isinstance(ports, list):
                continue
            for port in ports:
                if port not in labels:
                    raise ValueError(f"Task port '{port}' not declared in group networks.")

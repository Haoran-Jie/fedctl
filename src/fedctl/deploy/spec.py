from __future__ import annotations

from dataclasses import dataclass

from fedctl.constants import DEFAULT_FLWR_VERSION

from .network import NetworkPlan


@dataclass(frozen=True)
class SuperLinkSpec:
    node_class: str = "link"
    cpu: int = 500
    memory_mb: int = 256


@dataclass(frozen=True)
class SuperNodesSpec:
    count: int
    by_type: dict[str, int] | None = None
    allow_oversubscribe: bool = True
    prefer_spread_across_hosts: bool = True
    placements: list["SupernodePlacement"] | None = None
    network: NetworkPlan | None = None
    netem_image: str | None = None
    image: str | None = None
    resources_by_type: dict[str, dict[str, int]] | None = None
    default_resources: dict[str, int] | None = None
    node_class: str = "node"
    cpu: int = 500
    memory_mb: int = 512


@dataclass(frozen=True)
class SuperExecSpec:
    image: str
    serverapp_cpu: int = 1000
    serverapp_memory_mb: int = 1024
    clientapp_cpu: int = 1000
    clientapp_memory_mb: int = 1024
    user: str = "root"
    flwr_dir: str = "/tmp/.flwr"
    node_class_link: str = "link"
    node_class_node: str = "node"
    netem_serverapp: bool = True
    netem_clientapp: bool = True
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class DeploySpec:
    datacenter: str
    namespace: str
    experiment: str
    flwr_version: str
    insecure: bool
    superlink: SuperLinkSpec
    supernodes: SuperNodesSpec
    superexec: SuperExecSpec


def default_deploy_spec(
    num_supernodes: int = 2,
    *,
    image: str,
    flwr_version: str = DEFAULT_FLWR_VERSION,
    namespace: str = "default",
    experiment: str,
    supernodes_by_type: dict[str, int] | None = None,
    allow_oversubscribe: bool = True,
    prefer_spread_across_hosts: bool = True,
    placements: list["SupernodePlacement"] | None = None,
    network_plan: NetworkPlan | None = None,
    netem_image: str | None = None,
    supernode_image: str | None = None,
    resources_by_type: dict[str, dict[str, int]] | None = None,
    default_resources: dict[str, int] | None = None,
    superlink_resources: dict[str, int] | None = None,
    superexec_serverapp_resources: dict[str, int] | None = None,
    superexec_clientapp_resources: dict[str, int] | None = None,
    netem_serverapp: bool = True,
    netem_clientapp: bool = True,
    superexec_env: dict[str, str] | None = None,
) -> DeploySpec:
    superlink_cpu = int((superlink_resources or {}).get("cpu", SuperLinkSpec.cpu))
    superlink_memory_mb = int(
        (superlink_resources or {}).get("mem", SuperLinkSpec.memory_mb)
    )
    superexec_serverapp_cpu = int(
        (superexec_serverapp_resources or {}).get("cpu", SuperExecSpec.serverapp_cpu)
    )
    superexec_serverapp_memory_mb = int(
        (superexec_serverapp_resources or {}).get(
            "mem", SuperExecSpec.serverapp_memory_mb
        )
    )
    superexec_clientapp_cpu = int(
        (superexec_clientapp_resources or {}).get("cpu", SuperExecSpec.clientapp_cpu)
    )
    superexec_clientapp_memory_mb = int(
        (superexec_clientapp_resources or {}).get(
            "mem", SuperExecSpec.clientapp_memory_mb
        )
    )
    return DeploySpec(
        datacenter="dc1",
        namespace=namespace,
        experiment=experiment,
        flwr_version=flwr_version,
        insecure=True,
        superlink=SuperLinkSpec(
            cpu=superlink_cpu,
            memory_mb=superlink_memory_mb,
        ),
        supernodes=SuperNodesSpec(
            count=num_supernodes,
            by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            prefer_spread_across_hosts=prefer_spread_across_hosts,
            placements=placements,
            network=network_plan,
            netem_image=netem_image,
            image=supernode_image,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
        ),
        superexec=SuperExecSpec(
            image=image,
            serverapp_cpu=superexec_serverapp_cpu,
            serverapp_memory_mb=superexec_serverapp_memory_mb,
            clientapp_cpu=superexec_clientapp_cpu,
            clientapp_memory_mb=superexec_clientapp_memory_mb,
            netem_serverapp=netem_serverapp,
            netem_clientapp=netem_clientapp,
            env=superexec_env,
        ),
    )


def normalize_experiment_name(value: str) -> str:
    cleaned = value.strip().replace(" ", "-")
    return cleaned or "experiment"

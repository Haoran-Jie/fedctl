from __future__ import annotations

from dataclasses import dataclass

from .plan import SupernodePlacement


@dataclass(frozen=True)
class SuperLinkSpec:
    node_class: str = "link"
    cpu: int = 500
    memory_mb: int = 256


@dataclass(frozen=True)
class SuperNodesSpec:
    count: int
    by_type: dict[str, int] | None = None
    allow_oversubscribe: bool = False
    placements: list["SupernodePlacement"] | None = None
    resources_by_type: dict[str, dict[str, int]] | None = None
    default_resources: dict[str, int] | None = None
    node_class: str = "node"
    cpu: int = 500
    memory_mb: int = 512


@dataclass(frozen=True)
class SuperExecSpec:
    image: str
    cpu: int = 1000
    memory_mb: int = 1024
    user: str = "root"
    flwr_dir: str = "/tmp/.flwr"
    node_class_link: str = "link"
    node_class_node: str = "node"


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
    namespace: str = "default",
    experiment: str,
    supernodes_by_type: dict[str, int] | None = None,
    allow_oversubscribe: bool = False,
    placements: list["SupernodePlacement"] | None = None,
    resources_by_type: dict[str, dict[str, int]] | None = None,
    default_resources: dict[str, int] | None = None,
) -> DeploySpec:
    return DeploySpec(
        datacenter="dc1",
        namespace=namespace,
        experiment=experiment,
        flwr_version="1.23.0",
        insecure=True,
        superlink=SuperLinkSpec(),
        supernodes=SuperNodesSpec(
            count=num_supernodes,
            by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placements,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
        ),
        superexec=SuperExecSpec(image=image),
    )


def normalize_experiment_name(value: str) -> str:
    cleaned = value.strip().replace(" ", "-")
    return cleaned or "experiment"

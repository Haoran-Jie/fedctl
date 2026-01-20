from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuperLinkSpec:
    node_class: str = "link"
    cpu: int = 500
    memory_mb: int = 256


@dataclass(frozen=True)
class SuperNodesSpec:
    count: int
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
    flwr_version: str
    insecure: bool
    superlink: SuperLinkSpec
    supernodes: SuperNodesSpec
    superexec: SuperExecSpec


def default_deploy_spec(num_supernodes: int = 2, *, image: str) -> DeploySpec:
    return DeploySpec(
        datacenter="dc1",
        flwr_version="1.23.0",
        insecure=True,
        superlink=SuperLinkSpec(),
        supernodes=SuperNodesSpec(count=num_supernodes),
        superexec=SuperExecSpec(image=image),
    )

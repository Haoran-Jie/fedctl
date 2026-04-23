from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SuperlinkManifest:
    alloc_id: str
    node_id: str | None
    ports: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "alloc_id": self.alloc_id,
            "ports": self.ports,
        }
        if self.node_id is not None:
            data["node_id"] = self.node_id
        return data


@dataclass(frozen=True)
class DeploymentManifest:
    schema_version: int
    deployment_id: str
    experiment: str
    jobs: dict[str, object]
    superlink: SuperlinkManifest
    supernodes: SupernodesManifest | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema_version": self.schema_version,
            "deployment_id": self.deployment_id,
            "experiment": self.experiment,
            "jobs": self.jobs,
            "superlink": self.superlink.to_dict(),
        }
        if self.supernodes is not None:
            data["supernodes"] = self.supernodes.to_dict()
        return data


@dataclass(frozen=True)
class SupernodePlacementManifest:
    device_type: str | None
    instance_idx: int
    node_id: str | None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"instance_idx": self.instance_idx}
        if self.device_type is not None:
            data["device_type"] = self.device_type
        if self.node_id is not None:
            data["node_id"] = self.node_id
        return data


@dataclass(frozen=True)
class SupernodesNetworkManifest:
    default_profile: str
    profiles: dict[str, dict[str, float | int]]
    assignments: dict[str, list[str]]
    interface: str | None = None
    ingress_profiles: dict[str, dict[str, float | int]] | None = None
    egress_profiles: dict[str, dict[str, float | int]] | None = None
    ingress_assignments: dict[str, list[str]] | None = None
    egress_assignments: dict[str, list[str]] | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "default_profile": self.default_profile,
            "profiles": self.profiles,
            "assignments": self.assignments,
        }
        if self.interface:
            data["interface"] = self.interface
        if self.ingress_profiles:
            data["ingress_profiles"] = self.ingress_profiles
        if self.egress_profiles:
            data["egress_profiles"] = self.egress_profiles
        if self.ingress_assignments:
            data["ingress_assignments"] = self.ingress_assignments
        if self.egress_assignments:
            data["egress_assignments"] = self.egress_assignments
        return data


@dataclass(frozen=True)
class SupernodesManifest:
    requested_by_type: dict[str, int] | None
    allow_oversubscribe: bool
    placements: list[SupernodePlacementManifest]
    network: SupernodesNetworkManifest | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "requested_by_type": self.requested_by_type or {},
            "allow_oversubscribe": self.allow_oversubscribe,
            "placements": [p.to_dict() for p in self.placements],
        }
        if self.network is not None:
            data["network"] = self.network.to_dict()
        return data


def new_deployment_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

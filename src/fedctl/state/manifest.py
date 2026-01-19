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
    jobs: dict[str, object]
    superlink: SuperlinkManifest

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "deployment_id": self.deployment_id,
            "jobs": self.jobs,
            "superlink": self.superlink.to_dict(),
        }


def new_deployment_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

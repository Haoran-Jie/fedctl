from __future__ import annotations

from pathlib import Path

import pytest

from fedctl.state.manifest import DeploymentManifest, SuperlinkManifest, new_deployment_id
from fedctl.state.store import manifest_path, write_manifest
from fedctl.state.errors import StateError


def test_write_manifest_uses_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_user_config_dir() -> Path:
        return tmp_path

    monkeypatch.setattr("fedctl.state.store.user_config_dir", fake_user_config_dir)

    manifest = DeploymentManifest(
        schema_version=1,
        deployment_id=new_deployment_id(),
        experiment="trial",
        jobs={"superlink": "superlink"},
        superlink=SuperlinkManifest(
            alloc_id="alloc-1",
            node_id="node-1",
            ports={"control": 1},
        ),
    )

    path = write_manifest(manifest, namespace="exp1", experiment="trial")
    assert path == tmp_path / "state" / "exp1" / "trial" / "deploy.json"
    assert path.exists()


def test_write_manifest_overwrite_protection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_user_config_dir() -> Path:
        return tmp_path

    monkeypatch.setattr("fedctl.state.store.user_config_dir", fake_user_config_dir)

    manifest = DeploymentManifest(
        schema_version=1,
        deployment_id=new_deployment_id(),
        experiment="trial",
        jobs={"superlink": "superlink"},
        superlink=SuperlinkManifest(
            alloc_id="alloc-1",
            node_id=None,
            ports={"control": 1},
        ),
    )

    write_manifest(manifest, namespace="default", experiment="trial")
    with pytest.raises(StateError, match="Manifest already exists"):
        write_manifest(manifest, namespace="default", experiment="trial", overwrite=False)

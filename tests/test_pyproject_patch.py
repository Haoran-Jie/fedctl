from __future__ import annotations

from pathlib import Path

import tomlkit

from fedctl.project.pyproject_patch import patch_remote_deployment


def test_patch_remote_deployment_updates_address(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.flwr.federations]
default = "remote-deployment"
""".lstrip(),
        encoding="utf-8",
    )

    patch_remote_deployment(pyproject, address="192.168.1.10:27738", backup=False)

    doc = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    remote = doc["tool"]["flwr"]["federations"]["remote-deployment"]
    assert remote["address"] == "192.168.1.10:27738"
    assert remote["insecure"] is True


def test_patch_remote_deployment_creates_backup(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.flwr.federations.remote-deployment]
address = "old"
insecure = true
""".lstrip(),
        encoding="utf-8",
    )

    patch_remote_deployment(pyproject, address="new", backup=True)

    backup = tmp_path / "pyproject.toml.bak"
    assert backup.exists()

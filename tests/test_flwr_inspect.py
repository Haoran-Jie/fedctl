from __future__ import annotations

from pathlib import Path

import pytest

from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import inspect_flwr_project


def write_pyproject(tmp_path: Path, contents: str) -> Path:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(contents, encoding="utf-8")
    return pyproject_path


def test_inspect_flwr_project_happy_path(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"

[tool.flwr.app]
publisher = "acme"

[tool.flwr.app.components]
serverapp = "demo.server:app"
clientapp = "demo.client:app"

[tool.flwr.federations]
default = "remote-deployment"

[tool.flwr.federations.remote-deployment]
address = "127.0.0.1:9091"
insecure = true

[tool.flwr.federations.local-simulation.options]
num-supernodes = 3
""".lstrip(),
    )

    info = inspect_flwr_project(tmp_path)
    assert info.root == tmp_path
    assert info.publisher == "acme"
    assert info.serverapp == "demo.server:app"
    assert info.clientapp == "demo.client:app"
    assert info.federations_default == "remote-deployment"
    assert "remote-deployment" in info.federations
    assert info.project_name == "demo"
    assert info.project_version == "0.1.0"
    assert info.local_sim_num_supernodes == 3


def test_inspect_flwr_project_missing_pyproject(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="No pyproject.toml found"):
        inspect_flwr_project(tmp_path)


def test_inspect_flwr_project_malformed_toml(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.flwr.app")
    with pytest.raises(ProjectError, match="pyproject.toml is malformed"):
        inspect_flwr_project(tmp_path)


def test_inspect_flwr_project_missing_components(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.flwr.app]
publisher = "acme"
""".lstrip(),
    )
    with pytest.raises(ProjectError, match="Missing \\[tool.flwr.app.components\\].serverapp"):
        inspect_flwr_project(tmp_path)


def test_inspect_flwr_project_missing_serverapp(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.flwr.app.components]
clientapp = "demo.client:app"
""".lstrip(),
    )
    with pytest.raises(ProjectError, match="Missing \\[tool.flwr.app.components\\].serverapp"):
        inspect_flwr_project(tmp_path)


def test_inspect_flwr_project_missing_clientapp(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.flwr.app.components]
serverapp = "demo.server:app"
""".lstrip(),
    )
    with pytest.raises(ProjectError, match="Missing \\[tool.flwr.app.components\\].clientapp"):
        inspect_flwr_project(tmp_path)

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fedctl.project.flwr_inspect import FlwrProjectInfo, inspect_flwr_project, load_pyproject


@dataclass(frozen=True)
class BuildProjectInfo:
    root: Path
    pyproject_path: Path
    project_name: str
    project_version: str | None
    flwr_info: FlwrProjectInfo


def inspect_project(path: Path) -> BuildProjectInfo:
    root, doc = load_pyproject(path)
    pyproject_path = root / "pyproject.toml"
    flwr_info = inspect_flwr_project(root)

    project = doc.get("project", {}) if isinstance(doc.get("project"), dict) else {}
    name = project.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Missing [project].name in pyproject.toml.")

    version = project.get("version")
    if not isinstance(version, str):
        version = None

    return BuildProjectInfo(
        root=root,
        pyproject_path=pyproject_path,
        project_name=name,
        project_version=version,
        flwr_info=flwr_info,
    )

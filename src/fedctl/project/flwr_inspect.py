from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from .errors import ProjectError


@dataclass(frozen=True)
class FlwrProjectInfo:
    root: Path
    pyproject_path: Path
    publisher: str | None
    serverapp: str
    clientapp: str
    federations_default: str | None
    federations: dict[str, dict[str, Any]]
    project_name: str | None
    project_version: str | None
    local_sim_num_supernodes: int | None


def load_pyproject(path: Path) -> tuple[Path, dict[str, Any]]:
    if path.is_file():
        if path.name != "pyproject.toml":
            raise ProjectError(f"Expected pyproject.toml, got {path}.")
        pyproject_path = path
        root = path.parent
    else:
        pyproject_path = path / "pyproject.toml"
        root = path

    if not pyproject_path.exists():
        raise ProjectError(f"No pyproject.toml found at {pyproject_path}.")

    try:
        with pyproject_path.open("rb") as handle:
            doc = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"pyproject.toml is malformed: {exc}") from exc

    return root, doc


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_flwr_sections(
    doc: dict[str, Any], root: Path, pyproject_path: Path
) -> FlwrProjectInfo:
    tool = _as_dict(doc.get("tool"))
    flwr = _as_dict(tool.get("flwr"))
    app = _as_dict(flwr.get("app"))
    components = _as_dict(app.get("components"))

    serverapp = components.get("serverapp")
    if not serverapp:
        raise ProjectError("Missing [tool.flwr.app.components].serverapp.")

    clientapp = components.get("clientapp")
    if not clientapp:
        raise ProjectError("Missing [tool.flwr.app.components].clientapp.")

    publisher = app.get("publisher") if isinstance(app.get("publisher"), str) else None

    feds = _as_dict(flwr.get("federations"))
    federations_default = feds.get("default") if isinstance(feds.get("default"), str) else None
    federations: dict[str, dict[str, Any]] = {}
    for key, val in feds.items():
        if key == "default":
            continue
        if isinstance(val, dict):
            federations[key] = val

    local_sim = _as_dict(feds.get("local-simulation"))
    local_sim_options = _as_dict(local_sim.get("options"))
    local_sim_num_supernodes = local_sim_options.get("num-supernodes")
    if not isinstance(local_sim_num_supernodes, int):
        local_sim_num_supernodes = None

    project = _as_dict(doc.get("project"))
    project_name = project.get("name") if isinstance(project.get("name"), str) else None
    project_version = project.get("version") if isinstance(project.get("version"), str) else None

    return FlwrProjectInfo(
        root=root,
        pyproject_path=pyproject_path,
        publisher=publisher,
        serverapp=str(serverapp),
        clientapp=str(clientapp),
        federations_default=federations_default,
        federations=federations,
        project_name=project_name,
        project_version=project_version,
        local_sim_num_supernodes=local_sim_num_supernodes,
    )


def inspect_flwr_project(path: Path) -> FlwrProjectInfo:
    root, doc = load_pyproject(path)
    pyproject_path = root / "pyproject.toml"
    return extract_flwr_sections(doc, root=root, pyproject_path=pyproject_path)


def format_project_info(info: FlwrProjectInfo) -> str:
    federations = ", ".join(sorted(info.federations.keys())) or "-"
    default_fed = info.federations_default or "-"
    publisher = info.publisher or "-"
    local_sim = (
        str(info.local_sim_num_supernodes) if info.local_sim_num_supernodes is not None else "-"
    )
    return (
        "Flower project\n"
        f"  root: {info.root}\n"
        f"  publisher: {publisher}\n"
        f"  serverapp: {info.serverapp}\n"
        f"  clientapp: {info.clientapp}\n"
        f"  federations.default: {default_fed}\n"
        f"  federations: {federations}\n"
        f"  local-simulation.num-supernodes: {local_sim}"
    )

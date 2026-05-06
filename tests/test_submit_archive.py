from __future__ import annotations

import tarfile
from pathlib import Path

from fedctl.commands.submit import _build_project_archive


def _read_member_text(archive_path: Path, member_name: str) -> str:
    with tarfile.open(archive_path, "r:gz") as tar:
        member = tar.getmember(member_name)
        extracted = tar.extractfile(member)
        assert extracted is not None
        return extracted.read().decode("utf-8")


def test_archive_includes_profile_deploy_config_when_project_config_missing(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    external_cfg = tmp_path / "external-fedctl.yaml"
    external_cfg.write_text(
        "deploy:\n  placement:\n    allow_oversubscribe: true\n",
        encoding="utf-8",
    )

    archive_path = _build_project_archive(
        project_root,
        "demo",
        deploy_config_path=external_cfg,
    )

    archived_cfg = _read_member_text(
        archive_path,
        f"{project_root.name}/.fedctl/fedctl.yaml",
    )
    assert "allow_oversubscribe: true" in archived_cfg


def test_archive_uses_explicit_deploy_config_over_project_local_deploy_config(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    local_dir = project_root / ".fedctl"
    local_dir.mkdir()
    (local_dir / "fedctl.yaml").write_text(
        "deploy:\n  placement:\n    allow_oversubscribe: false\n",
        encoding="utf-8",
    )
    external_cfg = tmp_path / "external-fedctl.yaml"
    external_cfg.write_text(
        "deploy:\n  placement:\n    allow_oversubscribe: true\n",
        encoding="utf-8",
    )

    archive_path = _build_project_archive(
        project_root,
        "demo",
        deploy_config_path=external_cfg,
    )

    archived_cfg = _read_member_text(
        archive_path,
        f"{project_root.name}/.fedctl/fedctl.yaml",
    )
    assert "allow_oversubscribe: true" in archived_cfg


def test_archive_skips_unselected_config_trees_when_explicit_configs_are_supplied(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    run_config_dir = project_root / "run_configs"
    run_config_dir.mkdir()
    selected_run_config = run_config_dir / "selected.toml"
    selected_run_config.write_text("[run]\nmethod='fedavg'\n", encoding="utf-8")
    (run_config_dir / "unused.toml").write_text("[run]\nmethod='unused'\n", encoding="utf-8")
    deploy_config_dir = project_root / "deploy_configs"
    deploy_config_dir.mkdir()
    (deploy_config_dir / "unused.yaml").write_text("unused: true\n", encoding="utf-8")
    explicit_deploy_config = tmp_path / "explicit-fedctl.yaml"
    explicit_deploy_config.write_text(
        "deploy:\n  placement:\n    allow_oversubscribe: true\n",
        encoding="utf-8",
    )

    archive_path = _build_project_archive(
        project_root,
        "demo",
        deploy_config_path=explicit_deploy_config,
        run_config_path=selected_run_config,
        run_config_arcname="run_configs/selected.toml",
    )

    with tarfile.open(archive_path, "r:gz") as tar:
        members = {member.name for member in tar.getmembers()}

    assert f"{project_root.name}/run_configs/selected.toml" in members
    assert f"{project_root.name}/run_configs/unused.toml" not in members
    assert f"{project_root.name}/deploy_configs/unused.yaml" not in members
    assert f"{project_root.name}/.fedctl/fedctl.yaml" in members

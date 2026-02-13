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


def test_archive_includes_profile_repo_config_when_project_config_missing(
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
        repo_config_path=external_cfg,
    )

    archived_cfg = _read_member_text(
        archive_path,
        f"{project_root.name}/.fedctl/fedctl.yaml",
    )
    assert "allow_oversubscribe: true" in archived_cfg


def test_archive_prefers_project_local_repo_config_over_profile_repo_config(
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
        repo_config_path=external_cfg,
    )

    archived_cfg = _read_member_text(
        archive_path,
        f"{project_root.name}/.fedctl/fedctl.yaml",
    )
    assert "allow_oversubscribe: false" in archived_cfg

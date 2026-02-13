from __future__ import annotations

from pathlib import Path

from fedctl.commands.run import _resolve_run_repo_config


def test_resolve_run_repo_config_prefers_explicit_value(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    explicit = str(tmp_path / "external-fedctl.yaml")

    resolved = _resolve_run_repo_config(
        repo_config=explicit,
        project_root=project_root,
    )

    assert resolved == explicit


def test_resolve_run_repo_config_uses_project_local_config(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    local_cfg = project_root / ".fedctl" / "fedctl.yaml"
    local_cfg.parent.mkdir(parents=True)
    local_cfg.write_text("deploy: {}\n", encoding="utf-8")

    resolved = _resolve_run_repo_config(
        repo_config=None,
        project_root=project_root,
    )

    assert resolved == str(local_cfg)


def test_resolve_run_repo_config_returns_none_when_not_found(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    resolved = _resolve_run_repo_config(
        repo_config=None,
        project_root=project_root,
    )

    assert resolved is None

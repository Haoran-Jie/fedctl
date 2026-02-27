from __future__ import annotations

from pathlib import Path

from fedctl.config.io import ensure_config_exists, load_raw_toml, save_raw_toml
from fedctl.config.repo import resolve_repo_config, resolve_repo_config_path


def _use_tmp_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _set_default_profile_repo_config(path: Path) -> None:
    doc = load_raw_toml()
    doc["profiles"]["default"]["repo_config"] = str(path)
    save_raw_toml(doc)


def test_resolve_repo_config_path_prefers_explicit(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    explicit_cfg = tmp_path / "explicit-fedctl.yaml"
    explicit_cfg.write_text("submit:\n  image: explicit/image:latest\n", encoding="utf-8")

    resolved = resolve_repo_config_path(
        repo_config=str(explicit_cfg),
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == explicit_cfg.resolve()


def test_resolve_repo_config_path_uses_project_before_profile(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    resolved = resolve_repo_config_path(
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == project_cfg.resolve()


def test_resolve_repo_config_path_uses_profile_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    resolved = resolve_repo_config_path(
        include_profile=True,
    )
    assert resolved == profile_cfg.resolve()


def test_explicit_missing_repo_config_disables_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    missing_cfg = tmp_path / "missing-fedctl.yaml"
    resolved = resolve_repo_config(
        repo_config=str(missing_cfg),
        include_profile=True,
    )
    assert resolved.path is None
    assert resolved.data == {}

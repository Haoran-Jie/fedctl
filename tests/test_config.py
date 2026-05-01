from __future__ import annotations

from pathlib import Path

import tomlkit
import pytest
import yaml
from typer.testing import CliRunner

import fedctl.cli as cli
from fedctl.config.io import (
    DEFAULT_ARTIFACT_STORE,
    DEFAULT_CLUSTER_IMAGE_REGISTRY,
    DEFAULT_EXTERNAL_IMAGE_REGISTRY,
    DEFAULT_NOMAD_ENDPOINT,
    DEFAULT_SUBMIT_ENDPOINT,
    DEFAULT_SUBMIT_IMAGE,
    ensure_config_exists,
    load_config,
    load_raw_toml,
    save_raw_toml,
)
from fedctl.config.paths import deploy_default_config_path
from fedctl.config.merge import get_effective_config


def _use_tmp_xdg(monkeypatch, tmp_path: Path) -> Path:
    """Force config to live under tmp_path via XDG_CONFIG_HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_ensure_config_exists_creates_file(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    cfg_path = ensure_config_exists()
    assert cfg_path.exists()
    assert cfg_path.name == "config.toml"

    # sanity: file contains basic keys
    text = cfg_path.read_text()
    assert "active_profile" in text
    assert "profiles" in text


def test_load_config_creates_default_profile(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    cfg = load_config()

    assert cfg.active_profile == "default"
    assert "default" in cfg.profiles

    p = cfg.profiles["default"]
    assert p.endpoint == DEFAULT_NOMAD_ENDPOINT
    assert p.namespace == "default"
    assert p.deploy_config == str(deploy_default_config_path())


def test_default_config_writes_cammlsys_profile_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    cfg_path = ensure_config_exists()
    doc = tomlkit.parse(cfg_path.read_text())

    default_tbl = doc["profiles"]["default"]
    assert default_tbl["endpoint"] == DEFAULT_NOMAD_ENDPOINT
    assert default_tbl["namespace"] == "default"
    assert default_tbl["deploy_config"] == str(deploy_default_config_path())
    assert "repo_config" not in default_tbl


def test_profile_roundtrip_add_and_use(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    # Start from default
    _ = ensure_config_exists()

    # Simulate `fedctl profile add`
    doc = load_raw_toml()
    doc["profiles"]["lab-ts"] = {
        "endpoint": "https://nomad.lab.domain:4646",
        "namespace": "samuel",
    }
    save_raw_toml(doc)

    cfg = load_config()
    assert "lab-ts" in cfg.profiles
    assert cfg.profiles["lab-ts"].endpoint == "https://nomad.lab.domain:4646"
    assert cfg.profiles["lab-ts"].namespace == "samuel"

    # Simulate `fedctl profile use lab-ts`
    doc = load_raw_toml()
    doc["active_profile"] = "lab-ts"
    save_raw_toml(doc)

    cfg2 = load_config()
    assert cfg2.active_profile == "lab-ts"


def test_profile_add_writes_visible_deploy_config_key(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    deploy_cfg = tmp_path / "cluster.yaml"
    deploy_cfg.write_text("submit:\n  image: cluster:latest\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        [
            "profile",
            "add",
            "cluster",
            "--endpoint",
            "http://nomad.example:4646",
            "--deploy-config",
            str(deploy_cfg),
        ],
    )

    assert result.exit_code == 0
    doc = load_raw_toml()
    profile = doc["profiles"]["cluster"]
    assert profile["deploy_config"] == str(deploy_cfg.resolve())
    assert "repo_config" not in profile


def test_effective_config_precedence_flags_over_env_over_profile(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    _ = ensure_config_exists()

    # Add a profile with baseline values
    doc = load_raw_toml()
    doc["profiles"]["p1"] = {
        "endpoint": "http://profile-endpoint:4646",
        "namespace": "ns_profile",
    }
    doc["active_profile"] = "p1"
    save_raw_toml(doc)

    cfg = load_config()

    # Env overrides profile
    monkeypatch.setenv("FEDCTL_ENDPOINT", "http://env-endpoint:4646")
    monkeypatch.setenv("FEDCTL_NAMESPACE", "ns_env")

    eff_env = get_effective_config(cfg)
    assert eff_env.endpoint == "http://env-endpoint:4646"
    assert eff_env.namespace == "ns_env"

    # Flags override env
    eff_flags = get_effective_config(cfg, endpoint="http://flag-endpoint:4646", namespace="ns_flag")
    assert eff_flags.endpoint == "http://flag-endpoint:4646"
    assert eff_flags.namespace == "ns_flag"


def test_nomad_token_is_env_or_flag_only_not_persisted(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    _ = ensure_config_exists()

    cfg = load_config()

    # No token set
    monkeypatch.delenv("NOMAD_TOKEN", raising=False)
    eff1 = get_effective_config(cfg)
    assert eff1.nomad_token is None

    # Env token
    monkeypatch.setenv("NOMAD_TOKEN", "env-token-123")
    eff2 = get_effective_config(cfg)
    assert eff2.nomad_token == "env-token-123"

    # Flag token overrides env token
    eff3 = get_effective_config(cfg, token="flag-token-456")
    assert eff3.nomad_token == "flag-token-456"

    # Ensure token is not written into config file
    cfg_path = ensure_config_exists()
    doc = tomlkit.parse(cfg_path.read_text())
    assert "NOMAD_TOKEN" not in cfg_path.read_text()
    default_tbl = doc["profiles"]["default"]
    assert "nomad_token" not in default_tbl
    assert "env-token-123" not in cfg_path.read_text()
    assert "flag-token-456" not in cfg_path.read_text()


def test_effective_config_defaults_namespace_to_default_when_unset(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    _ = ensure_config_exists()
    cfg = load_config()
    monkeypatch.delenv("FEDCTL_NAMESPACE", raising=False)

    eff = get_effective_config(cfg)
    assert eff.namespace == "default"


def test_effective_config_treats_blank_namespace_as_default(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    _ = ensure_config_exists()

    doc = load_raw_toml()
    doc["profiles"]["default"]["namespace"] = "   "
    save_raw_toml(doc)
    cfg = load_config()

    monkeypatch.setenv("FEDCTL_NAMESPACE", "  ")
    eff = get_effective_config(cfg)
    assert eff.namespace == "default"


def test_unknown_profile_raises(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    cfg = load_config()

    with pytest.raises(ValueError):
        _ = get_effective_config(cfg, profile_name="does-not-exist")


def test_ensure_config_creates_default_deploy_config_file(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    monkeypatch.setenv("FEDCTL_SUBMIT_USER", "alice")

    _ = ensure_config_exists()
    deploy_cfg = deploy_default_config_path()
    assert deploy_cfg.exists()
    text = deploy_cfg.read_text(encoding="utf-8")
    assert "deploy:" in text
    assert "submit:" in text
    assert "submit-service:" in text

    data = yaml.safe_load(text)
    assert data["submit"]["image"] == DEFAULT_SUBMIT_IMAGE
    assert data["submit"]["artifact_store"] == DEFAULT_ARTIFACT_STORE
    assert data["submit"]["endpoint"] == DEFAULT_SUBMIT_ENDPOINT
    assert data["submit"]["token"] == ""
    assert data["submit"]["user"] == "alice"
    assert data["submit-service"]["image_registry"] == DEFAULT_CLUSTER_IMAGE_REGISTRY
    assert "nomad_endpoint" not in data["submit-service"]
    assert "dispatch_mode" not in data["submit-service"]
    assert data["image_registry"] == DEFAULT_EXTERNAL_IMAGE_REGISTRY
    assert "supernodes" not in data["deploy"]


def test_ensure_config_backfills_default_deploy_config_when_unset(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    cfg_path = ensure_config_exists()

    doc = tomlkit.parse(cfg_path.read_text())
    default_tbl = doc["profiles"]["default"]
    default_tbl.pop("deploy_config", None)
    default_tbl.pop("repo_config", None)
    cfg_path.write_text(tomlkit.dumps(doc))

    _ = ensure_config_exists()
    cfg = load_config()
    assert cfg.profiles["default"].deploy_config == str(deploy_default_config_path())


def test_ensure_config_migrates_legacy_repo_config_key(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    cfg_path = ensure_config_exists()

    legacy_path = tmp_path / "legacy.yaml"
    legacy_path.write_text("submit:\n  image: legacy:latest\n", encoding="utf-8")
    doc = tomlkit.parse(cfg_path.read_text())
    default_tbl = doc["profiles"]["default"]
    default_tbl.pop("deploy_config", None)
    default_tbl["repo_config"] = str(legacy_path)
    cfg_path.write_text(tomlkit.dumps(doc))

    _ = ensure_config_exists()
    migrated_doc = tomlkit.parse(cfg_path.read_text())
    migrated_default = migrated_doc["profiles"]["default"]
    assert migrated_default["deploy_config"] == str(legacy_path)
    assert "repo_config" not in migrated_default

    cfg = load_config()
    assert cfg.profiles["default"].deploy_config == str(legacy_path)

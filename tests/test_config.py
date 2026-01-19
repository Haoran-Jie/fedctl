from __future__ import annotations

from pathlib import Path

import tomlkit
import pytest

from fedctl.config.io import (
    ensure_config_exists,
    load_config,
    load_raw_toml,
    save_raw_toml,
)
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
    assert p.endpoint == "http://127.0.0.1:4646"
    assert p.access_mode == "lan-only"
    assert p.tls_skip_verify is False

    # Optional fields should load as None if omitted in TOML
    assert p.namespace is None
    assert p.tls_ca is None
    assert p.tailscale.subnet_cidr is None


def test_default_config_does_not_write_none_values(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    cfg_path = ensure_config_exists()
    doc = tomlkit.parse(cfg_path.read_text())

    # The keys should be omitted (rather than "namespace = None" which TOML can't represent)
    default_tbl = doc["profiles"]["default"]
    assert "namespace" not in default_tbl
    assert "tls_ca" not in default_tbl

    # tailscale table may exist, but should not contain subnet_cidr if unset
    if "tailscale" in default_tbl:
        assert "subnet_cidr" not in default_tbl["tailscale"]


def test_profile_roundtrip_add_and_use(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)

    # Start from default
    _ = ensure_config_exists()

    # Simulate `fedctl profile add`
    doc = load_raw_toml()
    doc["profiles"]["lab-ts"] = {
        "endpoint": "https://nomad.lab.domain:4646",
        "namespace": "samuel",
        "tls_ca": "/tmp/lab-ca.pem",
        "tls_skip_verify": False,
        "access_mode": "tailscale-subnet",
        "tailscale": {"subnet_cidr": "10.3.192.0/24"},
    }
    save_raw_toml(doc)

    cfg = load_config()
    assert "lab-ts" in cfg.profiles
    assert cfg.profiles["lab-ts"].endpoint == "https://nomad.lab.domain:4646"
    assert cfg.profiles["lab-ts"].namespace == "samuel"
    assert cfg.profiles["lab-ts"].access_mode == "tailscale-subnet"
    assert cfg.profiles["lab-ts"].tailscale.subnet_cidr == "10.3.192.0/24"

    # Simulate `fedctl profile use lab-ts`
    doc = load_raw_toml()
    doc["active_profile"] = "lab-ts"
    save_raw_toml(doc)

    cfg2 = load_config()
    assert cfg2.active_profile == "lab-ts"


def test_effective_config_precedence_flags_over_env_over_profile(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    _ = ensure_config_exists()

    # Add a profile with baseline values
    doc = load_raw_toml()
    doc["profiles"]["p1"] = {
        "endpoint": "http://profile-endpoint:4646",
        "namespace": "ns_profile",
        "tls_skip_verify": False,
        "access_mode": "lan-only",
        "tailscale": {},
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
    text = cfg_path.read_text()
    assert "NOMAD_TOKEN" not in text
    assert "nomad_token" not in text
    assert "env-token-123" not in text
    assert "flag-token-456" not in text


def test_unknown_profile_raises(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    cfg = load_config()

    with pytest.raises(ValueError):
        _ = get_effective_config(cfg, profile_name="does-not-exist")

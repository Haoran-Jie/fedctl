from __future__ import annotations

from types import SimpleNamespace

from fedctl.commands.submit import _runner_env


def _effective_config() -> SimpleNamespace:
    return SimpleNamespace(
        endpoint="http://127.0.0.1:4646",
        namespace="default",
        profile_name="default",
        nomad_token="nomad-token",
    )


def test_runner_env_excludes_docker_credentials(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_USERNAME", "user")
    monkeypatch.setenv("DOCKER_PASSWORD", "pass")
    monkeypatch.setenv("DOCKERHUB_USERNAME", "hub-user")
    monkeypatch.setenv("DOCKERHUB_TOKEN", "hub-token")
    monkeypatch.setenv("DOCKER_REGISTRY", "192.168.8.101:5000")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "aws-key")

    env = _runner_env(_effective_config())

    assert env["AWS_ACCESS_KEY_ID"] == "aws-key"
    assert "DOCKER_USERNAME" not in env
    assert "DOCKER_PASSWORD" not in env
    assert "DOCKERHUB_USERNAME" not in env
    assert "DOCKERHUB_TOKEN" not in env
    assert "DOCKER_REGISTRY" not in env

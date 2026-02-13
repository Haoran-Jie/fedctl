from __future__ import annotations

from typer.testing import CliRunner

import fedctl.cli as cli


def test_destroy_passes_remote_connection_options(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_destroy(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_destroy", fake_run_destroy)
    result = runner.invoke(
        cli.app,
        [
            "destroy",
            "exp-1",
            "--purge",
            "--profile",
            "cluster",
            "--endpoint",
            "http://192.168.8.101:4646",
            "--namespace",
            "samuel",
            "--token",
            "abc123",
            "--tls-ca",
            "/tmp/nomad-ca.pem",
            "--tls-skip-verify",
        ],
    )

    assert result.exit_code == 0
    assert captured["experiment"] == "exp-1"
    assert captured["destroy_all"] is False
    assert captured["purge"] is True
    assert captured["profile"] == "cluster"
    assert captured["endpoint"] == "http://192.168.8.101:4646"
    assert captured["namespace"] == "samuel"
    assert captured["token"] == "abc123"
    assert captured["tls_ca"] == "/tmp/nomad-ca.pem"
    assert captured["tls_skip_verify"] is True

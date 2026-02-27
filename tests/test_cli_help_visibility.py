from __future__ import annotations

from typer.testing import CliRunner

import fedctl.cli as cli


def test_help_hides_selected_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "│ submit" in result.output
    assert "│ deploy" in result.output
    assert "│ address" not in result.output
    assert "│ configure" not in result.output
    assert "│ inspect" not in result.output
    assert "│ config" not in result.output
    assert "│ logs" not in result.output
    assert "│ register" not in result.output


def test_help_orders_primary_commands_explicitly() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    order = [
        "│ submit",
        "│ destroy",
        "│ local",
        "│ profile",
        "│ run",
        "│ build",
        "│ deploy",
    ]
    positions = [result.output.index(token) for token in order]
    assert positions == sorted(positions)


def test_admin_command_executes(monkeypatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_destroy(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_destroy", fake_run_destroy)
    result = runner.invoke(cli.app, ["destroy", "exp-1"])

    assert result.exit_code == 0
    assert captured["experiment"] == "exp-1"


def test_hidden_command_still_executes(monkeypatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_configure(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_configure", fake_run_configure)
    result = runner.invoke(cli.app, ["configure", "."])

    assert result.exit_code == 0
    assert captured["path"] == "."

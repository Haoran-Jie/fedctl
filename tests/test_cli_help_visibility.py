from __future__ import annotations

from typer.testing import CliRunner

import fedctl.cli as cli
import fedctl.commands.configure as configure_commands
import fedctl.commands.destroy as destroy_commands


def test_help_hides_selected_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "│ submit" in result.output
    assert "│ deploy" not in result.output
    assert "│ destroy" not in result.output
    assert "│ local" not in result.output
    assert "│ profile" not in result.output
    assert "│ run" not in result.output
    assert "│ build" not in result.output
    assert "│ address" not in result.output
    assert "│ configure" not in result.output
    assert "│ inspect" not in result.output
    assert "│ config" not in result.output
    assert "│ logs" not in result.output
    assert "│ register" not in result.output


def test_help_only_shows_submit_command() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert result.output.count("│ submit") == 1


def test_admin_command_executes(monkeypatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_destroy(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(destroy_commands, "run_destroy", fake_run_destroy)
    result = runner.invoke(cli.app, ["destroy", "exp-1"])

    assert result.exit_code == 0
    assert captured["experiment"] == "exp-1"


def test_hidden_command_still_executes(monkeypatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_configure(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(configure_commands, "run_configure", fake_run_configure)
    result = runner.invoke(cli.app, ["configure", "."])

    assert result.exit_code == 0
    assert captured["path"] == "."


def test_retired_hidden_commands_no_longer_execute() -> None:
    runner = CliRunner()

    for command in ("address", "logs", "register", "inspect"):
        result = runner.invoke(cli.app, [command, "--help"])
        assert result.exit_code != 0

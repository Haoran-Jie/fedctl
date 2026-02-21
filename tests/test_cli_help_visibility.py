from __future__ import annotations

import importlib

from typer.testing import CliRunner

import fedctl.cli as cli


def _reload_cli(monkeypatch, show_admin_help: str | None):
    if show_admin_help is None:
        monkeypatch.delenv("FEDCTL_SHOW_ADMIN_HELP", raising=False)
    else:
        monkeypatch.setenv("FEDCTL_SHOW_ADMIN_HELP", show_admin_help)
    return importlib.reload(cli)


def test_help_is_submit_first_by_default(monkeypatch) -> None:
    module = _reload_cli(monkeypatch, None)
    runner = CliRunner()
    result = runner.invoke(module.app, ["--help"])

    assert result.exit_code == 0
    assert "│ submit" in result.output
    assert "│ deploy" not in result.output
    assert "│ config" not in result.output


def test_help_shows_admin_commands_with_toggle(monkeypatch) -> None:
    module = _reload_cli(monkeypatch, "1")
    runner = CliRunner()
    result = runner.invoke(module.app, ["--help"])

    assert result.exit_code == 0
    assert "│ submit" in result.output
    assert "│ deploy" in result.output
    assert "│ config" in result.output


def test_hidden_admin_command_still_executes(monkeypatch) -> None:
    module = _reload_cli(monkeypatch, None)
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run_destroy(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(module, "run_destroy", fake_run_destroy)
    result = runner.invoke(module.app, ["destroy", "exp-1"])

    assert result.exit_code == 0
    assert captured["experiment"] == "exp-1"

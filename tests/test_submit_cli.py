from __future__ import annotations

from typer.testing import CliRunner

import fedctl.cli as cli
import fedctl.commands.submit as submit_commands


def test_submit_allows_options_after_path(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(submit_commands, "run_submit", fake_run_submit)
    result = runner.invoke(cli.app, ["submit", "run", "../proj", "--exp", "testexp"])
    assert result.exit_code == 0
    assert captured["path"] == "../proj"
    assert captured["experiment"] == "testexp"


def test_submit_run_uses_visible_deploy_config_option(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(submit_commands, "run_submit", fake_run_submit)
    result = runner.invoke(
        cli.app,
        ["submit", "run", "../proj", "--deploy-config", "cluster.yaml"],
    )
    assert result.exit_code == 0
    assert captured["deploy_config"] == "cluster.yaml"


def test_submit_run_accepts_hidden_legacy_repo_config_option(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(submit_commands, "run_submit", fake_run_submit)
    result = runner.invoke(
        cli.app,
        ["submit", "run", "../proj", "--repo-config", "cluster.yaml"],
    )
    assert result.exit_code == 0
    assert captured["deploy_config"] == "cluster.yaml"


def test_submit_run_help_hides_legacy_repo_config_option() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["submit", "run", "--help"])

    assert result.exit_code == 0
    assert "--deploy-config" in result.output
    assert "--repo-config" not in result.output


def test_submit_cancel_routes_to_runner(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit_cancel(*, submission_id: str):
        captured["submission_id"] = submission_id
        return 0

    monkeypatch.setattr(submit_commands, "run_submit_cancel", fake_run_submit_cancel)
    result = runner.invoke(cli.app, ["submit", "cancel", "sub-123"])
    assert result.exit_code == 0
    assert captured["submission_id"] == "sub-123"


def test_submit_purge_routes_optional_submission_id(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit_purge(*, submission_id: str | None):
        captured["submission_id"] = submission_id
        return 0

    monkeypatch.setattr(submit_commands, "run_submit_purge", fake_run_submit_purge)

    result = runner.invoke(cli.app, ["submit", "purge", "sub-123"])
    assert result.exit_code == 0
    assert captured["submission_id"] == "sub-123"

    result = runner.invoke(cli.app, ["submit", "purge"])
    assert result.exit_code == 0
    assert captured["submission_id"] is None


def test_submit_ls_routes_status_filter(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit_ls(*, limit: int, status_filter: str):
        captured["limit"] = limit
        captured["status_filter"] = status_filter
        return 0

    monkeypatch.setattr(submit_commands, "run_submit_ls", fake_run_submit_ls)

    result = runner.invoke(cli.app, ["submit", "ls", "--completed", "--limit", "7"])
    assert result.exit_code == 0
    assert captured["limit"] == 7
    assert captured["status_filter"] == "completed"

    result = runner.invoke(cli.app, ["submit", "ls"])
    assert result.exit_code == 0
    assert captured["status_filter"] == "active"


def test_submit_ls_rejects_multiple_status_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["submit", "ls", "--active", "--all"])
    assert result.exit_code != 0
    assert "Choose only one status flag" in result.output

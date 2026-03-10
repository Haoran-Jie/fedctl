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

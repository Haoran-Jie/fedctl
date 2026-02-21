from __future__ import annotations

from typer.testing import CliRunner

import fedctl.cli as cli


def test_submit_allows_options_after_path(monkeypatch) -> None:
    runner = CliRunner()
    captured = {}

    def fake_run_submit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_submit", fake_run_submit)
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

    monkeypatch.setattr(cli, "run_submit_cancel", fake_run_submit_cancel)
    result = runner.invoke(cli.app, ["submit", "cancel", "sub-123"])
    assert result.exit_code == 0
    assert captured["submission_id"] == "sub-123"

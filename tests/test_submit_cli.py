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

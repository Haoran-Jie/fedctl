from typer.testing import CliRunner

import fedctl.cli as cli


def test_help_shows_usage() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "fedctl" in result.output


def test_version_option(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "_fedctl_version", lambda: "9.9.9")

    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == "9.9.9"

from typer.testing import CliRunner

from fedctl.cli import app


def test_help_shows_usage() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "fedctl" in result.output

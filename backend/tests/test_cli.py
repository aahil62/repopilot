from typer.testing import CliRunner

from repopilot.cli import app


def test_help_lists_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["serve", "index", "review", "blast", "nightshift", "bench", "models"]:
        assert name in result.output

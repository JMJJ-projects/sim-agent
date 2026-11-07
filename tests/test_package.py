"""Smoke tests for the package scaffold."""

from typer.testing import CliRunner

import photonsim
import simagent
from simagent.cli import app


def test_packages_import() -> None:
    assert photonsim.__doc__
    assert simagent.__version__


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert simagent.__version__ in result.stdout

"""Command-line interface (`simagent`)."""

import typer

from simagent import __version__

app = typer.Typer(
    name="simagent",
    help="Natural language to sandboxed photon-transport simulations.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Natural language to sandboxed photon-transport simulations."""


@app.command()
def version() -> None:
    """Print the simagent version."""
    typer.echo(__version__)

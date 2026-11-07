"""Command-line interface (``simagent``).

Exit codes (R-CLI-4): 0 solved / ok, 3 not solved / refused / run failed, 2 invalid input or
configuration (including a missing sandbox), 1 unexpected error. Expected failures print one
line, without a stack trace.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from simagent import __version__
from simagent.config import ConfigError, Settings, load_env
from simagent.doctor import run_checks
from simagent.execution import Execution, execute
from simagent.runners import RunnerUnavailableError, make_runner

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_NOT_SOLVED = 3

app = typer.Typer(
    name="simagent",
    help="Natural language to sandboxed photon-transport simulations.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
out = Console()
err = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


def expected_errors(func: F) -> F:
    """Turn configuration and sandbox-availability errors into one line and exit code 2."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (ConfigError, RunnerUnavailableError) as exc:
            err.print(f"[bold red]error:[/] {exc}", highlight=False, soft_wrap=True)
            raise typer.Exit(EXIT_CONFIG) from None

    return wrapper  # type: ignore[return-value]


@app.callback()
def main() -> None:
    """Natural language to sandboxed photon-transport simulations."""
    load_env()


@app.command()
def version() -> None:
    """Print the simagent version."""
    typer.echo(__version__)


def _execution_dict(ex: Execution) -> dict[str, Any]:
    run = ex.run
    return {
        "ok": ex.ok,
        "failure": ex.failure,
        "policy_violations": [str(v) for v in ex.policy.violations],
        "run": None
        if run is None
        else {
            "runner": run.runner,
            "exit_code": run.exit_code,
            "timed_out": run.timed_out,
            "duration_s": round(run.duration_s, 3),
            "result": run.result_json,
            "result_error": run.result_error,
            "stdout": run.stdout,
            "stderr": run.stderr,
        },
    }


def _print_execution(ex: Execution) -> None:
    if not ex.policy.ok:
        out.print(Panel(ex.policy.feedback(), title="policy: rejected", border_style="red"))
        return
    run = ex.run
    assert run is not None
    style = "green" if ex.ok else "red"
    status = "ok" if ex.ok else f"failed: {ex.failure}"
    table = Table.grid(padding=(0, 2))
    table.add_row("status", f"[{style}]{status}[/]")
    table.add_row("runner", run.runner)
    table.add_row("duration", f"{run.duration_s:.2f} s")
    if run.result_json is not None:
        table.add_row("answer", json.dumps(run.result_json.get("answer")))
    out.print(Panel(table, title="run-script", border_style=style))
    if run.stdout.strip():
        out.print(Panel(run.stdout.rstrip(), title="stdout", border_style="dim"))
    if run.stderr.strip():
        out.print(Panel(run.stderr.rstrip(), title="stderr", border_style="dim"))


@app.command("run-script")
@expected_errors
def run_script(
    file: Annotated[Path, typer.Argument(help="Python script to check and run.")],
    unsafe_local: Annotated[
        bool, typer.Option("--unsafe-local", help="Run without isolation (development only).")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print a JSON report.")] = False,
) -> None:
    """Run a script through the static policy and the sandbox only (no model)."""
    if not file.is_file():
        raise ConfigError(f"file not found: {file}")
    try:
        code = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"{file} is not a UTF-8 text file") from None
    settings = Settings.from_env()
    runner = make_runner(unsafe_local=unsafe_local, limits=settings.limits)
    ex = execute(code, runner, timeout_s=settings.timeout_s)
    if as_json:
        typer.echo(json.dumps(_execution_dict(ex), indent=2))
    else:
        if ex.run is not None and ex.run.warnings:
            for w in ex.run.warnings:
                err.print(f"[yellow]{w}[/]", highlight=False)
        _print_execution(ex)
        if ex.policy.ok:
            out.print(Syntax(code, "python", line_numbers=True, word_wrap=True))
    raise typer.Exit(EXIT_OK if ex.ok else EXIT_NOT_SOLVED)


@app.command()
@expected_errors
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Print a JSON report.")] = False,
) -> None:
    """Check Docker, the sandbox image, Ollama, the GPU and which API keys are set."""
    checks = run_checks(Settings.from_env())
    missing = [c for c in checks if c.required and not c.ok]
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {"name": c.name, "ok": c.ok, "required": c.required, "detail": c.detail}
                    for c in checks
                ],
                indent=2,
            )
        )
    else:
        table = Table(title="simagent doctor", show_lines=False)
        table.add_column("check")
        table.add_column("status")
        table.add_column("detail", overflow="fold")
        for c in checks:
            mark = "[green]ok[/]" if c.ok else ("[red]missing[/]" if c.required else "[yellow]-[/]")
            table.add_row(c.name, mark, c.detail)
        out.print(table)
        if missing:
            err.print(f"[bold red]error:[/] {missing[0].detail}", highlight=False, soft_wrap=True)
    raise typer.Exit(EXIT_CONFIG if missing else EXIT_OK)

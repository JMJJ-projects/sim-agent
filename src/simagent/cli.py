"""Command-line interface (``simagent``).

Exit codes (R-CLI-4): 0 solved / ok, 3 not solved / refused / run failed / answered but not
verified (``solved_unverified``), 2 invalid input or
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
from simagent.agent import run_agent
from simagent.config import ConfigError, Settings, load_env
from simagent.doctor import run_checks
from simagent.execution import Execution, execute
from simagent.prompts import validate_request
from simagent.runners import RunnerUnavailableError, make_runner
from simagent.state import FinalAnswer

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
        typer.echo(json.dumps(ex.to_dict(), indent=2))
    else:
        if ex.run is not None and ex.run.warnings:
            for w in ex.run.warnings:
                err.print(f"[yellow]{w}[/]")
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


def _final_json(final: FinalAnswer, run_dir: Path | None) -> dict[str, Any]:
    out_dict: dict[str, Any] = dict(final)
    out_dict["files"] = sorted(final["files"])
    out_dict["run_dir"] = str(run_dir) if run_dir else None
    return out_dict


def _tok(value: object) -> str:
    return "not reported" if value is None else str(value)


def _error_summary(text: str | None, width: int = 110) -> str:
    """One line for an error report: the exception line of a traceback, else the first line."""
    if not text:
        return ""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    has_traceback = any(ln.startswith("stderr") for ln in lines)
    line = lines[-1] if has_traceback else lines[0]
    if line.endswith(":") and len(lines) > 1:  # policy / verification feedback: first bullet
        line = lines[1].removeprefix("- ")
    return line if len(line) <= width else line[: width - 3] + "..."


def print_final(final: FinalAnswer, run_dir: Path | None, console: Console | None = None) -> None:
    """Rich summary of a final answer (also used by scripts/render_demo.py)."""
    con = console or out
    status = final["status"]
    style = {"solved": "green", "refused": "yellow", "solved_unverified": "yellow"}.get(
        status, "red"
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_row("status", f"[bold {style}]{status}[/]")
    grid.add_row("attempts", str(final["attempts"]))
    if status in ("solved", "solved_unverified"):
        grid.add_row("answer", json.dumps(final["answer"]))
        if final["data"]:
            grid.add_row("data", json.dumps(final["data"], default=str)[:600])
    for finding in final.get("findings") or []:
        mark = "[red]fail[/]" if finding["severity"] == "fail" else "[yellow]warn[/]"
        grid.add_row(finding["check"], f"{mark} {finding['message']}")
    if final["explanation"]:
        grid.add_row("explanation", final["explanation"])
    if run_dir is not None:
        grid.add_row("artifacts", str(run_dir))
    if final["files"]:
        where = f" (saved under {run_dir})" if run_dir else ""
        grid.add_row("files", ", ".join(sorted(final["files"])) + where)
    con.print(Panel(grid, title=f"simagent solve: {final['request'][:60]}", border_style=style))

    table = Table(title="attempts", show_lines=False)
    table.add_column("#")
    table.add_column("outcome", overflow="fold")
    calls = final["metrics"]
    for i, error in enumerate(final["errors"], start=1):
        table.add_row(str(i), _error_summary(error) or "[green]ok[/]")
    table.caption = (
        f"model {calls['model_s']:.1f} s, sandbox {calls['run_s']:.1f} s, "
        f"tokens in/out {_tok(calls['input_tokens'])}/{_tok(calls['output_tokens'])}"
    )
    con.print(table)
    if final["final_script"]:
        con.print(Panel(Syntax(final["final_script"], "python", line_numbers=True), title="script"))


@app.command()
@expected_errors
def solve(
    request: Annotated[str, typer.Argument(help="What to simulate, in plain language.")],
    provider: Annotated[
        str | None, typer.Option(help="ollama | groq | openai | fake (default: LLM_PROVIDER).")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model name (default: LLM_MODEL).")] = None,
    max_attempts: Annotated[
        int, typer.Option("--max-attempts", help="Attempts including the first (1 = baseline).")
    ] = 4,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="baseline (one attempt) | repair (fix failed runs) | verify (also check the "
            "answer against the request and the simulation trace).",
        ),
    ] = "repair",
    unsafe_local: Annotated[
        bool, typer.Option("--unsafe-local", help="Run without isolation (development only).")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the final answer as JSON.")
    ] = False,
) -> None:
    """Turn a request into a simulation script, run it in the sandbox and repair it if needed."""
    try:
        text = validate_request(request)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    settings = Settings.from_env(provider=provider, model=model)
    if settings.provider == "fake" and not as_json:
        demo = (
            "a crash, then a script that runs but uses the wrong unit, then the fix"
            if mode == "verify"
            else "a buggy script, then the fix"
        )
        err.print(
            f"[dim]note: --provider fake replays a built-in scripted demo ({demo}); the request "
            "text does not change the code.[/]",
            highlight=False,
        )
    if unsafe_local:
        err.print("[yellow]warning: --unsafe-local runs generated code without isolation[/]")
    final, run_dir = run_agent(
        text, settings, max_attempts=max_attempts, mode=mode, unsafe_local=unsafe_local
    )
    if as_json:
        typer.echo(json.dumps(_final_json(final, run_dir), indent=2, default=str))
    else:
        print_final(final, run_dir)
    raise typer.Exit(EXIT_OK if final["status"] == "solved" else EXIT_NOT_SOLVED)  # R-CLI-4


@app.command()
@expected_errors
def mcp(
    provider: Annotated[
        str | None, typer.Option(help="Provider used by the solve tool (default: LLM_PROVIDER).")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model name (default: LLM_MODEL).")] = None,
) -> None:
    """Start the MCP server on stdio (tools: describe_simulator, run_simulation_script, solve)."""
    from simagent.mcp_server import build_server

    settings = Settings.from_env(provider=provider, model=model)
    err.print(
        f"simagent MCP server on stdio (provider {settings.provider}); Ctrl+C to stop",
        highlight=False,
    )
    build_server(settings).run("stdio")

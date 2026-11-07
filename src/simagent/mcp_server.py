"""MCP server exposing the simulator, sandbox and agent as tools (R-MCP-1, R-MCP-2).

Tools:

* ``describe_simulator()``: the photonsim API reference, the result contract and the limits.
* ``run_simulation_script(code)``: static policy + sandbox run of a client-written script.
* ``solve(request, max_attempts=4)``: the full self-correcting agent.

The runner, timeout and resource limits come from the server's configuration. No tool takes
them as arguments, and unknown arguments (e.g. ``timeout_s``) are dropped by the SDK before the
tool runs, so a client cannot override them (R-MCP-2). Blocking work runs in a worker thread.

Uses the official ``mcp`` SDK 2.x (``MCPServer``, formerly ``FastMCP``), stdio transport.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from photonsim.apidoc import render as render_api
from simagent import __version__, prompts
from simagent.agent import check_runner, validate_max_attempts
from simagent.artifacts import ArtifactWriter
from simagent.config import Settings
from simagent.execution import execute
from simagent.graph import solve as solve_graph
from simagent.nodes import AgentDeps
from simagent.policy import ALLOWED_MODULES
from simagent.runners import Runner, RunnerUnavailableError, make_runner

INSTRUCTIONS = """\
Photon-transport simulation tools. Call describe_simulator first: it returns the photonsim API
and the result contract. Use run_simulation_script to run your own script (it must call
simagent_io.submit(answer, **data)), or solve to let the server's agent write, run and repair
a script for a plain-language request. Scripts are checked by a static policy and run in an
isolated sandbox; limits are fixed by the server."""

DepsFactory = Callable[[Settings, Runner], AgentDeps]


@contextmanager
def expected_failures() -> Iterator[None]:
    """Report anticipated failures (bad input, config, missing sandbox) to the client.

    The SDK hides the text of any other exception from the client, which is right for crashes.
    """
    try:
        yield
    except (ValueError, RunnerUnavailableError) as exc:  # ConfigError is a ValueError
        raise ToolError(str(exc)) from exc


def describe(settings: Settings) -> str:
    lim = settings.limits
    limits = (
        "# Execution limits (fixed by the server)\n\n"
        f"- timeout: {settings.timeout_s:g} s per run\n"
        f"- memory: {lim.memory_mb} MB, CPUs: {lim.cpus:g}, processes: {lim.pids}\n"
        "- no network; read-only filesystem except /tmp and /out; non-root\n"
        f"- allowed imports: {', '.join(sorted(ALLOWED_MODULES))}\n"
        "- PNG files written to /out (1 MB total) are returned\n"
    )
    return f"{render_api()}\n{prompts.IO_CONTRACT}\n{limits}"


def _default_deps(settings: Settings, runner: Runner) -> AgentDeps:
    from simagent.llm import make_chat_model, resolve_model

    return AgentDeps(
        model=make_chat_model(settings),
        runner=runner,
        provider=settings.provider,
        model_name=resolve_model(settings),
        timeout_s=settings.timeout_s,
    )


def build_server(
    settings: Settings | None = None,
    *,
    runner: Runner | None = None,
    deps_factory: DepsFactory | None = None,
    preflight: bool = True,
) -> MCPServer:
    """Create the MCP server. ``runner``/``deps_factory`` are injection points for tests."""
    cfg = settings or Settings.from_env()
    run_with = runner or make_runner(limits=cfg.limits)
    make_deps = deps_factory or _default_deps
    server = MCPServer(
        "simagent", instructions=INSTRUCTIONS, version=__version__, title="Simulation agent"
    )

    def _preflight() -> None:
        if preflight:
            check_runner(run_with)

    @server.tool()
    def describe_simulator() -> str:
        """The photonsim API reference, the simagent_io result contract and the sandbox limits."""
        return describe(cfg)

    @server.tool()
    async def run_simulation_script(code: str) -> dict[str, Any]:
        """Check a Python script with the static policy and run it in the sandbox.

        The script must call simagent_io.submit(answer, **data). Returns the policy verdict,
        exit code, stdout/stderr (capped), the submitted result and any PNG files (base64).
        """
        with expected_failures():
            _preflight()
        ex = await anyio.to_thread.run_sync(lambda: execute(code, run_with, cfg.timeout_s))
        return ex.to_dict(include_files=True)

    @server.tool()
    async def solve(request: str, max_attempts: int = 4) -> dict[str, Any]:
        """Turn a plain-language request into a simulation, run it and repair it if it fails.

        max_attempts counts the first attempt (1 = no repair); the server caps it at 10.
        Returns status, answer, data, explanation, final script, attempts and errors.
        """
        with expected_failures():
            text = prompts.validate_request(request)
            attempts = validate_max_attempts(max_attempts)
            _preflight()

        def _run() -> dict[str, Any]:
            deps = make_deps(cfg, run_with)
            writer = ArtifactWriter(
                cfg.runs_dir,
                {"provider": deps.provider, "model": deps.model_name, "via": "mcp"},
            )
            deps.hooks.append(writer)
            final = solve_graph(text, deps, max_attempts=attempts)
            out: dict[str, Any] = dict(final)
            out["files"] = sorted(final["files"])
            out["run_dir"] = str(writer.dir)
            return out

        return await anyio.to_thread.run_sync(_run)

    return server


def main() -> None:  # pragma: no cover - exercised manually / by MCP clients
    """Entry point for ``simagent mcp``: serve over stdio."""
    build_server().run("stdio")

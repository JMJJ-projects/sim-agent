"""MCP tools exercised through an in-process MCP client (R-MCP-1, R-MCP-2)."""

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from simagent.config import Settings
from simagent.demo import DEMO_REPLIES
from simagent.llm import ScriptedChatModel
from simagent.mcp_server import build_server
from simagent.nodes import AgentDeps
from simagent.runners import LocalRunner
from simagent.runners.base import Runner, RunResult

GOOD = (
    "import photonsim as ps, simagent_io\n"
    "r = ps.simulate(ps.Slab([ps.Layer('lead', 1.0)]), 1.0, 2000, seed=1)\n"
    "simagent_io.submit(r.transmitted, stderr=r.stderr_transmitted)\n"
)


class Recording(Runner):
    """Offline stand-in for the sandbox that records what it was asked to run."""

    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.inner = LocalRunner(enabled=True)
        self.timeouts: list[float] = []

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        self.timeouts.append(timeout_s)
        return self.inner.run(code, timeout_s=timeout_s)


@pytest.fixture
def runner() -> Recording:
    return Recording()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(provider="fake", timeout_s=17.0, runs_dir=tmp_path / "runs")


def _server(settings: Settings, runner: Runner) -> Any:
    def deps(cfg: Settings, run_with: Runner) -> AgentDeps:
        return AgentDeps(
            model=ScriptedChatModel(replies=list(DEMO_REPLIES)),
            runner=run_with,
            provider="fake",
            model_name="scripted",
            timeout_s=cfg.timeout_s,
        )

    return build_server(settings, runner=runner, deps_factory=deps, preflight=False)


def _call(server: Any, name: str, args: dict[str, Any] | None = None) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, args or {})

    return anyio.run(go)


def _json(result: Any) -> Any:
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_lists_three_tools_without_limit_arguments(settings: Settings, runner: Recording) -> None:
    """Covers R-MCP-1 and R-MCP-2: no tool accepts a timeout, runner or limit."""

    async def go() -> Any:
        async with Client(_server(settings, runner)) as client:
            return await client.list_tools(), client.instructions

    tools, instructions = anyio.run(go)
    by_name = {t.name: t for t in tools.tools}
    assert set(by_name) == {"describe_simulator", "run_simulation_script", "solve"}
    assert set(by_name["run_simulation_script"].input_schema["properties"]) == {"code"}
    assert set(by_name["solve"].input_schema["properties"]) == {
        "request",
        "max_attempts",
        "verify",
    }
    assert by_name["describe_simulator"].input_schema.get("properties", {}) == {}
    assert instructions is not None
    assert "describe_simulator" in instructions


def test_describe_simulator(settings: Settings, runner: Recording) -> None:
    text = _call(_server(settings, runner), "describe_simulator").content[0].text
    assert "photonsim API reference" in text
    assert "simagent_io.submit(answer, **data)" in text
    assert "timeout: 17 s" in text


def test_run_simulation_script_ok(settings: Settings, runner: Recording) -> None:
    report = _json(_call(_server(settings, runner), "run_simulation_script", {"code": GOOD}))
    assert report["ok"] is True
    assert 0 < report["run"]["result"]["answer"] < 1
    assert runner.timeouts == [17.0]


def test_run_simulation_script_policy_blocks(settings: Settings, runner: Recording) -> None:
    """Covers R-MCP-2: the same static policy as the CLI; nothing runs."""
    code = "import matplotlib\nmatplotlib.subprocess.run(['id'])\n"
    report = _json(_call(_server(settings, runner), "run_simulation_script", {"code": code}))
    assert report["ok"] is False
    assert report["failure"] == "policy violation"
    assert report["run"] is None
    assert runner.timeouts == []


def test_client_cannot_override_limits(settings: Settings, runner: Recording) -> None:
    """Covers R-MCP-2: extra arguments are ignored; the configured timeout is used."""
    args = {"code": GOOD, "timeout_s": 100000, "memory_mb": 64000, "unsafe_local": True}
    report = _json(_call(_server(settings, runner), "run_simulation_script", args))
    assert report["ok"] is True
    assert runner.timeouts == [17.0]


def test_solve_runs_the_agent(settings: Settings, runner: Recording) -> None:
    """Covers R-MCP-1: the full agent, with a repair, through MCP."""
    final = _json(_call(_server(settings, runner), "solve", {"request": "5 cm of water"}))
    assert final["status"] == "solved"
    assert final["attempts"] == 2
    assert "unknown material 'H2O'" in final["errors"][0]
    assert Path(final["run_dir"], "trace.json").is_file()
    assert runner.timeouts == [17.0, 17.0]
    assert final["findings"] == []  # verified by default (R-VER-6)


def test_solve_reports_verification_findings(settings: Settings, runner: Recording) -> None:
    """Covers R-VER-6: verify is on by default and its findings are returned."""
    request = {"request": "5 cm of lead at 1 MeV", "max_attempts": 2}
    final = _json(_call(_server(settings, runner), "solve", request))
    assert final["status"] == "solved_unverified"  # the scripted demo always simulates water
    assert {f["check"] for f in final["findings"]} >= {"V-MATERIAL"}
    off = _json(_call(_server(settings, runner), "solve", {**request, "verify": False}))
    assert off["status"] == "solved"
    assert off["findings"] == []


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"request": "x", "max_attempts": 0}, "between 1 and 10"),
        ({"request": "x", "max_attempts": 50}, "between 1 and 10"),
        ({"request": "   "}, "empty"),
    ],
)
def test_solve_rejects_bad_arguments(
    settings: Settings, runner: Recording, args: dict[str, Any], message: str
) -> None:
    result = _call(_server(settings, runner), "solve", args)
    assert result.is_error
    assert message in result.content[0].text
    assert runner.timeouts == []


def test_preflight_reports_missing_sandbox(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from simagent.runners import DockerRunner, docker

    monkeypatch.setattr(docker, "docker_executable", lambda: None)
    server = build_server(settings, runner=DockerRunner())
    result = _call(server, "run_simulation_script", {"code": GOOD})
    assert result.is_error
    assert "sandbox not available" in result.content[0].text


@pytest.mark.docker
def test_run_simulation_script_in_docker(settings: Settings) -> None:
    """Covers R-MCP-2: MCP uses the same Docker sandbox as the CLI."""
    from simagent.runners import DockerRunner

    server = build_server(settings, runner=DockerRunner())
    report = _json(_call(server, "run_simulation_script", {"code": GOOD}))
    assert report["ok"] is True
    assert report["run"]["runner"] == "docker"

"""Tests for `simagent solve` (R-CLI-1, R-CLI-4) and agent assembly pre-flight checks."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simagent import agent
from simagent.cli import app
from simagent.config import ConfigError, Settings
from simagent.runners import docker
from simagent.runners.local import ENV_FLAG

cli = CliRunner()
REQ = "transmission of 1 MeV photons through 5 cm of water"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in [ENV_FLAG, "LLM_PROVIDER", "LLM_MODEL"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SIMAGENT_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr("simagent.cli.load_env", lambda: None)


def test_fake_demo_solves_with_repair(tmp_path: Path) -> None:
    """Covers R-CLI-1: offline demo with a full repair cycle."""
    res = cli.invoke(app, ["solve", REQ, "--provider", "fake", "--unsafe-local", "--json"])
    assert res.exit_code == 0, res.output
    final = json.loads(res.stdout)
    assert final["status"] == "solved"
    assert final["attempts"] == 2
    assert "unknown material 'H2O'" in final["errors"][0]
    assert 0 < final["answer"] < 1
    run_dir = Path(final["run_dir"])
    assert (run_dir / "trace.json").is_file()
    assert run_dir.parent == tmp_path / "runs"


def test_rich_output(tmp_path: Path) -> None:
    res = cli.invoke(app, ["solve", REQ, "--provider", "fake", "--unsafe-local"])
    assert res.exit_code == 0, res.output
    assert "solved" in res.stdout
    assert "unknown material 'H2O'" in res.stdout
    assert "scripted demo" in res.stderr


def test_baseline_failure_exit_3() -> None:
    """Covers R-CLI-4 and R-AG-5."""
    res = cli.invoke(
        app,
        ["solve", REQ, "--provider", "fake", "--unsafe-local", "--max-attempts", "1", "--json"],
    )
    assert res.exit_code == 3
    assert json.loads(res.stdout)["status"] == "failed"


@pytest.mark.parametrize("args", [["solve", "  "], ["solve", REQ, "--max-attempts", "0"]])
def test_invalid_input_exit_2(args: list[str]) -> None:
    res = cli.invoke(app, [*args, "--provider", "fake", "--unsafe-local"])
    assert res.exit_code == 2
    assert "error:" in res.stderr


def test_without_docker_one_line_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-CLI-4: without Docker, solve explains what is missing."""
    monkeypatch.setattr(docker, "docker_executable", lambda: None)
    res = cli.invoke(app, ["solve", REQ, "--provider", "fake"])
    assert res.exit_code == 2
    assert "sandbox not available" in res.stderr
    assert "Traceback" not in res.output


def test_ollama_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(ConfigError, match="not reachable"):
        agent.check_model(Settings.from_env(provider="ollama", model="m"))


def test_ollama_model_not_pulled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "ollama_models", lambda url: ["llama3.2:3b"])
    with pytest.raises(ConfigError, match=re.escape("ollama pull qwen2.5-coder:3b")):
        agent.check_model(Settings.from_env(provider="ollama", model="qwen2.5-coder:3b"))
    agent.check_model(Settings.from_env(provider="ollama", model="llama3.2:3b"))


def test_latest_tag_matches_bare_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "ollama_models", lambda url: ["phi4-mini:latest"])
    agent.check_model(Settings.from_env(provider="ollama", model="phi4-mini"))


def test_hosted_provider_skips_ollama_check() -> None:
    agent.check_model(Settings.from_env(provider="groq", model="m"))


def test_render_demo_from_recorded_run(tmp_path: Path) -> None:
    """The demo SVG is rendered from a saved run's artifacts (PLAN 8.1)."""
    import importlib.util

    res = cli.invoke(app, ["solve", REQ, "--provider", "fake", "--unsafe-local", "--json"])
    assert res.exit_code == 0, res.output
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "render_demo", root / "scripts" / "render_demo.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "demo.svg"
    assert mod.main(["--search", str(tmp_path / "runs"), "--out", str(out)]) == 0
    svg = out.read_text(encoding="utf-8")
    assert svg.startswith("<svg")
    assert "H2O" in svg
    assert mod.main(["--search", str(tmp_path / "nothing"), "--out", str(out)]) == 2


def test_fake_verify_demo_catches_the_wrong_unit() -> None:
    """Covers R-VER-6 and PLAN-v2 4.4: the offline demo shows a wrong answer caught."""
    args = ["solve", REQ, "--provider", "fake", "--unsafe-local", "--mode", "verify", "--json"]
    res = cli.invoke(app, args)
    assert res.exit_code == 0, res.output
    final = json.loads(res.stdout)
    assert final["status"] == "solved"
    assert final["attempts"] == 3
    assert "unknown material 'H2O'" in final["errors"][0]
    assert "[V-LENGTH]" in final["errors"][1]
    assert final["findings"] == []


def test_verify_output_shows_the_finding() -> None:
    res = cli.invoke(
        app, ["solve", REQ, "--provider", "fake", "--unsafe-local", "--mode", "verify"]
    )
    assert res.exit_code == 0, res.output
    assert "[V-LENGTH]" in res.stdout
    assert "wrong unit" in res.stderr


def test_baseline_mode_uses_one_attempt() -> None:
    args = ["solve", REQ, "--provider", "fake", "--unsafe-local", "--mode", "baseline", "--json"]
    res = cli.invoke(app, args)
    assert res.exit_code == 3
    assert json.loads(res.stdout)["attempts"] == 1


def test_unknown_mode_is_a_config_error() -> None:
    res = cli.invoke(app, ["solve", REQ, "--provider", "fake", "--unsafe-local", "--mode", "x"])
    assert res.exit_code == 2


def test_unverified_answer_is_shown_with_its_findings() -> None:
    """Covers R-VER-5 and R-CLI-4: answered but unverified exits 3 and lists the findings."""
    from rich.console import Console

    from simagent.cli import print_final

    final: dict[str, object] = {
        "status": "solved_unverified",
        "request": REQ,
        "answer": 0.97,
        "data": {},
        "explanation": "",
        "final_script": None,
        "attempts": 4,
        "errors": [None],
        "refusal": None,
        "files": {},
        "metrics": {
            "model_s": 0.0,
            "run_s": 0.0,
            "input_tokens": None,
            "output_tokens": None,
        },
        "findings": [
            {"check": "V-LENGTH", "severity": "fail", "message": "5 cm was never simulated"},
            {"check": "V-MONOTONE", "severity": "warn", "message": "odd curve"},
        ],
    }
    console = Console(record=True, width=120)
    print_final(final, None, console)  # type: ignore[arg-type]
    text = console.export_text()
    assert "solved_unverified" in text
    assert "0.97" in text
    assert "V-LENGTH" in text
    assert "5 cm was never simulated" in text
    assert "warn odd curve" in text

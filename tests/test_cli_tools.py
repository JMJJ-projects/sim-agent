"""Tests for `simagent run-script`, `simagent doctor`, config and the execute helper."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simagent import doctor
from simagent.cli import app
from simagent.config import ConfigError, Settings
from simagent.execution import execute
from simagent.runners import docker
from simagent.runners.base import Runner, RunResult
from simagent.runners.local import ENV_FLAG

GOOD = (
    "import photonsim as ps, simagent_io\n"
    "r = ps.simulate(ps.Slab([ps.Layer('lead', 1.0)]), 1.0, 2000, seed=1)\n"
    "simagent_io.submit(r.transmitted)\n"
)
cli = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in [ENV_FLAG, "LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("simagent.cli.load_env", lambda: None)


def _write(tmp_path: Path, code: str) -> Path:
    path = tmp_path / "script.py"
    path.write_text(code, encoding="utf-8")
    return path


class NeverRunner(Runner):
    name = "never"

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        raise AssertionError("runner must not be called")


def test_execute_policy_blocks_before_running() -> None:
    """Covers R-POL-4 and R-AG-8: a violation never reaches the runner."""
    ex = execute("import os\n", NeverRunner())
    assert not ex.ok
    assert ex.run is None
    assert ex.failure == "policy violation"


def test_run_script_ok_with_local_runner(tmp_path: Path) -> None:
    """Covers R-CLI-2."""
    res = cli.invoke(app, ["run-script", str(_write(tmp_path, GOOD)), "--unsafe-local", "--json"])
    assert res.exit_code == 0, res.output
    report = json.loads(res.stdout)
    assert report["ok"] is True
    assert report["run"]["runner"] == "local-unsafe"
    assert 0 < report["run"]["result"]["answer"] < 1


def test_run_script_rich_output(tmp_path: Path) -> None:
    res = cli.invoke(app, ["run-script", str(_write(tmp_path, GOOD)), "--unsafe-local"])
    assert res.exit_code == 0, res.output
    assert "answer" in res.stdout
    assert "WARNING" in res.stderr


def test_run_script_failed_run_exit_3(tmp_path: Path) -> None:
    """Covers R-CLI-4."""
    res = cli.invoke(app, ["run-script", str(_write(tmp_path, "print(1)\n")), "--unsafe-local"])
    assert res.exit_code == 3
    assert "no result submitted" in res.stdout


def test_run_script_policy_violation_exit_3(tmp_path: Path) -> None:
    """Covers R-CLI-2 and R-CLI-4."""
    res = cli.invoke(app, ["run-script", str(_write(tmp_path, "import os\n")), "--unsafe-local"])
    assert res.exit_code == 3
    assert "import of `os` is not allowed" in res.stdout


def test_run_script_missing_file_exit_2(tmp_path: Path) -> None:
    res = cli.invoke(app, ["run-script", str(tmp_path / "nope.py")])
    assert res.exit_code == 2
    assert "file not found" in res.stderr


def test_run_script_without_docker_one_line_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers R-CLI-4: expected failure, one line, no stack trace."""
    monkeypatch.setattr(docker, "docker_executable", lambda: None)
    res = cli.invoke(app, ["run-script", str(_write(tmp_path, GOOD))])
    assert res.exit_code == 2
    assert "Docker is not available" in res.stderr
    assert "Traceback" not in res.output
    assert len(res.stderr.strip().splitlines()) <= 3  # one logical line, may soft-wrap


def _no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor, "docker_status", lambda: (False, False, "docker CLI not found on PATH")
    )


def test_doctor_without_docker_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-CLI-3."""
    _no_docker(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    res = cli.invoke(app, ["doctor"])
    assert res.exit_code == 2
    assert "docker CLI not found" in res.stderr
    assert "ollama" in res.stdout


def test_doctor_never_prints_key_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-CLI-3 and R-LLM-4."""
    _no_docker(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_super_secret_value")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    res = cli.invoke(app, ["doctor", "--json"])
    assert "gsk_super_secret_value" not in res.output
    checks = {c["name"]: c for c in json.loads(res.stdout)}
    assert checks["GROQ_API_KEY"]["detail"] == "present"
    assert checks["OPENAI_API_KEY"]["detail"] == "absent"


def test_doctor_ok_when_docker_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "docker_status", lambda: (True, True, "image present"))
    monkeypatch.setattr(doctor, "ollama_models", lambda url: ["qwen2.5-coder:3b"])
    res = cli.invoke(app, ["doctor", "--json"])
    assert res.exit_code == 0
    checks = {c["name"]: c for c in json.loads(res.stdout)}
    assert checks["sandbox image"]["ok"]
    assert "qwen2.5-coder:3b" in checks["ollama"]["detail"]


def test_doctor_gpu_check_without_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert not doctor.check_gpu().ok


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ConfigError, match="unknown provider"):
        Settings.from_env(provider="nope")


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "m")
    s = Settings.from_env()
    assert (s.provider, s.model) == ("groq", "m")
    assert Settings.from_env(provider="fake").provider == "fake"

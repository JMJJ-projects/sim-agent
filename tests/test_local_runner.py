"""Tests for the opt-in unsafe local runner."""

import pytest

from simagent.runners import DockerRunner, LocalRunner, RunnerUnavailableError, make_runner
from simagent.runners.local import ENV_FLAG, WARNING


@pytest.fixture(autouse=True)
def _no_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_FLAG, raising=False)


def test_disabled_by_default() -> None:
    """Covers R-SBX-8."""
    with pytest.raises(RunnerUnavailableError, match="--unsafe-local"):
        LocalRunner()


def test_factory_defaults_to_docker() -> None:
    """Covers R-SBX-2."""
    assert isinstance(make_runner(), DockerRunner)


def test_enabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_FLAG, "1")
    assert isinstance(make_runner(), LocalRunner)


def test_runs_script_and_warns(capsys: pytest.CaptureFixture[str]) -> None:
    """Covers R-SBX-8: prints a warning on every run."""
    runner = make_runner(unsafe_local=True)
    code = (
        "import photonsim as ps, simagent_io\n"
        "r = ps.simulate(ps.Slab([ps.Layer('water', 1.0)]), 1.0, 1000, seed=1)\n"
        "print('hello')\n"
        "simagent_io.submit(r.transmitted, n=r.n_photons)\n"
    )
    for _ in range(2):
        res = runner.run(code, timeout_s=60)
        assert res.ok, res.stderr
        assert res.stdout.strip() == "hello"
        assert res.result_json is not None
        assert res.result_json["data"] == {"n": 1000}
        assert res.warnings == [WARNING]
    assert capsys.readouterr().err.count(WARNING) == 2


def test_host_secrets_not_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-local-secret")
    res = make_runner(unsafe_local=True).run(
        "import os, simagent_io\nsimagent_io.submit(os.environ.get('GROQ_API_KEY'))\n"
    )
    assert res.result_json == {"answer": None, "data": {}}


def test_timeout() -> None:
    res = make_runner(unsafe_local=True).run("while True:\n    pass\n", timeout_s=1)
    assert res.timed_out
    assert res.failure == "timed out"


def test_error_and_missing_result() -> None:
    runner = make_runner(unsafe_local=True)
    err = runner.run("raise ValueError('boom')\n")
    assert err.exit_code == 1
    assert "ValueError: boom" in err.stderr
    none = runner.run("print(1)\n")
    assert none.exit_code == 0
    assert "no result submitted" in (none.failure or "")


def test_local_runner_returns_the_trace() -> None:
    """The local runner turns recording on like the sandbox image does (R-TRACE-1)."""
    code = (
        "import simagent_io\nimport photonsim as ps\n"
        "r = ps.simulate(ps.Slab([ps.Layer('water', 4.0)]), 0.5, 100, seed=1)\n"
        "simagent_io.submit(r.transmitted)\n"
    )
    res = LocalRunner(enabled=True).run(code)
    assert res.ok
    assert res.trace is not None
    assert [c["layers"] for c in res.trace["calls"]] == [[["water", 4.0]]]

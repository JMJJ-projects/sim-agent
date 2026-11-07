"""Tests for the evaluation runner and summary metrics (R-EV-5, R-EV-6, R-EV-8)."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from simagent.config import ConfigError
from simagent.evaluation import harness
from simagent.evaluation.expected import load_expected
from simagent.evaluation.harness import EvalConfig, cost_usd, fake_model_factory, run_eval
from simagent.evaluation.summary import read_records, summarise
from simagent.evaluation.tasks import Task, load_tasks
from simagent.llm import ScriptedChatModel
from simagent.runners import LocalRunner
from simagent.runners.base import Runner, RunResult

ROOT = Path(__file__).resolve().parents[1]
TASKS = load_tasks(ROOT / "data" / "tasks.jsonl")
EXPECTED = load_expected(ROOT / "data" / "expected.json")["tasks"]


class Delegating(Runner):
    """Offline stand-in for the sandbox in tests (wraps the local runner)."""

    name = "test-delegating"

    def __init__(self) -> None:
        super().__init__()
        self.inner = LocalRunner(enabled=True)

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        return self.inner.run(code, timeout_s=timeout_s)


def _cfg(tmp_path: Path, **kw: Any) -> EvalConfig:
    args: dict[str, Any] = {
        "provider": "fake",
        "model": "scripted",
        "mode": "repair",
        "results_dir": tmp_path / "results",
        "runs_dir": tmp_path / "runs",
    }
    args.update(kw)
    return EvalConfig(**args)


def _pick(*ids: str) -> list[Task]:
    return [t for t in TASKS if t.id in ids]


def test_fake_eval_end_to_end_and_resume(tmp_path: Path) -> None:
    """Covers R-EV-5 and R-EV-8: one line per task, resumable."""
    tasks = _pick("single_01", "ambig_01", "adv_01")
    cfg = _cfg(tmp_path, limit=2)
    factory = fake_model_factory(ROOT)
    first = run_eval(cfg, tasks, EXPECTED, Delegating(), factory)
    assert [r["task_id"] for r in first] == ["single_01", "ambig_01"]
    assert all(r["passed"] for r in first)
    lines = cfg.results_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    with pytest.raises(ConfigError, match="--resume"):
        run_eval(_cfg(tmp_path), tasks, EXPECTED, Delegating(), factory)

    second = run_eval(_cfg(tmp_path, resume=True), tasks, EXPECTED, Delegating(), factory)
    assert [r["task_id"] for r in second] == ["adv_01"]
    assert second[0]["status"] == "refused"
    assert second[0]["passed"]
    records = read_records(cfg.results_path)
    assert len(records) == 3
    rec = records[0]
    assert rec["attempt_outcomes"] == ["ok"]
    assert rec["input_tokens"] is None
    assert rec["cost_usd"] is None
    assert Path(rec["run_dir"], "trace.json").is_file()


def test_baseline_mode_uses_one_attempt(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, mode="baseline")
    assert cfg.attempts_for_mode == 1
    assert cfg.name == "fake-scripted-p1-baseline"


def test_local_runner_rejected(tmp_path: Path) -> None:
    """Covers R-SBX-8: never used in the evaluation."""
    with pytest.raises(ConfigError, match="unsafe local runner"):
        run_eval(_cfg(tmp_path), TASKS, EXPECTED, LocalRunner(enabled=True), lambda t: None)  # type: ignore[arg-type,return-value]


def test_invalid_mode(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mode"):
        run_eval(_cfg(tmp_path, mode="x"), TASKS, EXPECTED, Delegating(), lambda t: None)  # type: ignore[arg-type,return-value]


def test_missing_expected_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="make_expected"):
        run_eval(_cfg(tmp_path), _pick("single_01"), {}, Delegating(), fake_model_factory(ROOT))


class Exploding(Runner):
    name = "exploding"

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        raise RuntimeError("sandbox vanished")


def test_harness_error_recorded_and_run_continues(tmp_path: Path) -> None:
    tasks = _pick("single_01", "adv_01")
    records = run_eval(_cfg(tmp_path), tasks, EXPECTED, Exploding(), fake_model_factory(ROOT))
    assert records[0]["status"] == "error"
    assert not records[0]["passed"]
    assert "sandbox vanished" in records[0]["harness_error"]
    assert records[1]["passed"]


def test_cost_from_dated_price_table() -> None:
    prices = {"models": {"groq/m": {"input_per_mtok": 0.5, "output_per_mtok": 1.0}}}
    assert cost_usd(prices, "groq", "m", 2_000_000, 1_000_000) == pytest.approx(2.0)
    assert cost_usd(prices, "groq", "other", 10, 10) is None
    assert cost_usd(prices, "groq", "m", None, 10) is None


def test_run_name_is_file_safe() -> None:
    assert harness.run_name_for("ollama", "qwen2.5-coder:3b", "repair", 2) == (
        "ollama-qwen2.5-coder_3b-p2-repair"
    )


class RateLimitedModel(ScriptedChatModel):
    """Raises a rate-limit error for the first ``limit`` calls, then replies."""

    limit: int = 1
    _n: int = 0

    def _next(self, messages: Any) -> str:
        type(self)._n += 1
        if type(self)._n <= self.limit:
            raise RuntimeError("Error code: 429 - rate_limit_exceeded")
        return super()._next(messages)


def test_rate_limited_task_is_retried(tmp_path: Path) -> None:
    tasks = _pick("adv_01")
    RateLimitedModel._n = 0
    reply = harness.fake_reply(tasks[0], ROOT)
    cfg = _cfg(tmp_path, rate_limit_wait_s=0.0)
    records = run_eval(
        cfg, tasks, EXPECTED, Delegating(), lambda t: RateLimitedModel(replies=[reply])
    )
    assert records[0]["passed"]
    assert records[0]["rate_limit_retries"] == 1
    assert records[0]["prompt_version"] == 1


def test_persistent_rate_limit_is_recorded_as_failure(tmp_path: Path) -> None:
    tasks = _pick("single_01")
    RateLimitedModel._n = 0
    cfg = _cfg(tmp_path, rate_limit_wait_s=0.0, rate_limit_retries=1)
    records = run_eval(
        cfg, tasks, EXPECTED, Delegating(), lambda t: RateLimitedModel(replies=[], limit=99)
    )
    assert not records[0]["passed"]
    assert records[0]["attempt_outcomes"] == ["model_error"]
    assert records[0]["rate_limit_retries"] == 1


def test_vram_sampler_without_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    with harness.VramSampler() as s:
        pass
    assert s.peak_mib is None


def _rec(**kw: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "task_id": "t",
        "category": "single_run",
        "provider": "ollama",
        "model": "m",
        "mode": "repair",
        "max_attempts": 4,
        "status": "solved",
        "passed": True,
        "attempts": 1,
        "policy_violations": 0,
        "timeouts": 0,
        "latency_s": 10.0,
        "input_tokens": 100,
        "output_tokens": 50,
        "ttft_s": [1.0],
        "tokens_per_s": [40.0],
        "cost_usd": None,
        "peak_vram_mib": None,
    }
    rec.update(kw)
    return rec


def test_summary_metrics() -> None:
    """Covers R-EV-6."""
    records = [
        _rec(task_id="a", attempts=1, latency_s=10.0),
        _rec(task_id="b", attempts=3, latency_s=20.0, policy_violations=1, ttft_s=[1.0, 3.0]),
        _rec(task_id="c", category="sweep", passed=False, status="solved", latency_s=30.0),
        _rec(task_id="d", category="sweep", passed=False, status="failed", timeouts=2),
    ]
    s = summarise(records)
    assert s["tasks"] == 4
    assert s["success_rate"] == 0.5
    assert s["success_rate_by_category"] == {"single_run": 1.0, "sweep": 0.0}
    assert s["mean_attempts_solved"] == 2.0
    assert s["repaired_successes"] == 1
    assert s["status_solved_but_wrong"] == 1
    assert s["policy_violations"] == 1
    assert s["timeouts"] == 2
    assert s["latency_median_s"] == 15.0
    assert s["ttft_median_s"] == 1.0
    assert s["input_tokens_total"] == 400
    assert s["cost_usd_total"] is None
    assert s["peak_vram_mib"] is None


def test_summary_nulls_when_unreported() -> None:
    s = summarise([_rec(input_tokens=None, ttft_s=[None], tokens_per_s=[None])])
    assert s["input_tokens_total"] is None
    assert s["ttft_median_s"] is None
    assert s["tokens_per_s_median"] is None
    assert summarise([])["success_rate"] is None


def test_read_records_last_wins(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    lines = [json.dumps(_rec(task_id="a", passed=False)), "", json.dumps(_rec(task_id="a"))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [r["passed"] for r in read_records(path)] == [True]


@pytest.mark.docker
def test_evaluate_script_smoke(tmp_path: Path) -> None:
    """Covers R-EV-8: the CI smoke run, through the real script and the Docker sandbox."""
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = ["--provider", "fake", "--mode", "repair", "--limit", "3"]
    args += ["--results-dir", str(tmp_path / "results"), "--runs-dir", str(tmp_path / "runs")]
    assert module.main(args) == 0
    summary = json.loads(
        (tmp_path / "results" / "fake-scripted-repair.summary.json").read_text(encoding="utf-8")
    )
    assert summary["tasks"] == 3

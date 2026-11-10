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
from simagent.prompts import PROMPT_VERSION_LATEST
from simagent.runners import LocalRunner
from simagent.runners.base import Runner, RunnerUnavailableError, RunResult

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
    assert len(lines) == 3  # header + one line per task

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
    free = {"models": {"groq/f": {"input_per_mtok": None, "output_per_mtok": None, "note": "n/a"}}}
    assert cost_usd(free, "groq", "f", 10, 10) is None
    assert harness.price_note(free, "groq", "f") == "n/a"
    assert harness.price_note(prices, "groq", "m") is None


def test_v2_run_names_carry_task_set_and_seed(tmp_path: Path) -> None:
    """Covers R-STAT-1: one results file per (configuration, task set, seed)."""
    assert harness.run_name_for("ollama", "qwen2.5-coder:3b", "verify", 3, "heldout", 4) == (
        "ollama-qwen2.5-coder_3b-p3-verify-heldout-s4"
    )
    assert harness.run_name_for("fake", "m", "repair", 1) == "fake-m-p1-repair"  # v1
    assert _cfg(tmp_path, seed=2).name == "fake-scripted-p1-repair-dev-s2"
    assert _cfg(tmp_path, run_name="ci", seed=0, task_set="heldout").name == "ci-heldout-s0"
    assert _cfg(tmp_path, run_name="ci").name == "ci"


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


def _evaluate_module() -> Any:
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluate_parses_seeds_and_task_sets() -> None:
    """Covers R-STAT-1."""
    ev = _evaluate_module()
    assert ev.parse_seeds("0,1, 2") == [0, 1, 2]
    for bad in ("", "a", "0,0", "-1"):
        with pytest.raises(ConfigError, match="--seeds"):
            ev.parse_seeds(bad)
    assert ev.task_set_names("all") == ["dev", "heldout"]
    assert ev.task_set_names("heldout") == ["heldout"]
    args = ev.parse_args(["--mode", "repair"])
    assert args.temperature == 0.7  # R-STAT-2
    assert args.seeds == "0"
    assert args.results_dir == ROOT / "results" / "v2"


def test_evaluate_rejects_bad_temperature() -> None:
    ev = _evaluate_module()
    assert ev.main(["--provider", "fake", "--mode", "repair", "--temperature", "3"]) == 2


@pytest.mark.docker
def test_evaluate_script_smoke(tmp_path: Path) -> None:
    """Covers R-EV-8, R-STAT-1: one results file per (task set, seed), through the real script
    and the Docker sandbox; resume works per file and refuses changed settings."""
    ev = _evaluate_module()
    args = ["--provider", "fake", "--mode", "repair", "--limit", "2"]
    args += ["--task-set", "all", "--seeds", "0,1"]
    args += ["--results-dir", str(tmp_path / "results"), "--runs-dir", str(tmp_path / "runs")]
    assert ev.main(args) == 0
    for task_set in ("dev", "heldout"):
        for seed in (0, 1):
            name = harness.run_name_for(
                "fake", "scripted", "repair", PROMPT_VERSION_LATEST, task_set, seed
            )
            path = tmp_path / "results" / f"{name}.jsonl"
            header = harness.read_header(path)
            assert header is not None
            assert (header["task_set"], header["seed"], header["temperature"]) == (
                task_set,
                seed,
                0.7,
            )
            summary = json.loads(
                (tmp_path / "results" / f"{name}.summary.json").read_text(encoding="utf-8")
            )
            assert summary["tasks"] == 2
    assert ev.main([*args, "--resume"]) == 0  # nothing left to do
    assert ev.main([*args, "--resume", "--temperature", "0.2"]) == 2


def test_results_file_starts_with_sampling_header(tmp_path: Path) -> None:
    """Covers R-STAT-2: every results file records its sampling settings in a header line."""
    cfg = _cfg(
        tmp_path,
        task_set="heldout",
        temperature=0.7,
        seed=3,
        seed_supported=False,
        model_digest="abc",
        quantization="Q4_K_M",
        code_commit="deadbeef",
    )
    records = run_eval(cfg, _pick("single_01"), EXPECTED, Delegating(), fake_model_factory(ROOT))
    lines = cfg.results_path.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert harness.is_header(header)
    assert harness.read_header(cfg.results_path) == header
    expected_fields = {
        "provider": "fake",
        "model": "scripted",
        "model_digest": "abc",
        "quantization": "Q4_K_M",
        "mode": "repair",
        "task_set": "heldout",
        "temperature": 0.7,
        "seed": 3,
        "seed_supported": False,
        "prompt_version": cfg.prompt_version,
        "max_attempts": 4,
        "code_commit": "deadbeef",
    }
    assert {k: header[k] for k in expected_fields} == expected_fields
    assert len(lines) == 2
    assert records[0]["seed"] == 3
    assert records[0]["temperature"] == 0.7
    assert records[0]["task_set"] == "heldout"
    assert [r["task_id"] for r in read_records(cfg.results_path)] == ["single_01"]
    assert harness.done_task_ids(cfg.results_path) == {"single_01"}


def test_resume_refuses_different_settings(tmp_path: Path) -> None:
    """Covers R-STAT-1/2: a resumed file never mixes seeds or temperatures."""
    tasks = _pick("single_01", "ambig_01")
    factory = fake_model_factory(ROOT)
    run_eval(
        _cfg(tmp_path, seed=0, temperature=0.7, limit=1), tasks, EXPECTED, Delegating(), factory
    )
    with pytest.raises(ConfigError, match=r"temperature: file 0.7 vs now 0.2"):
        run_eval(
            _cfg(tmp_path, seed=0, temperature=0.2, resume=True),
            tasks,
            EXPECTED,
            Delegating(),
            factory,
        )
    more = run_eval(
        _cfg(tmp_path, seed=0, temperature=0.7, resume=True, code_commit="other"),
        tasks,
        EXPECTED,
        Delegating(),
        factory,
    )
    assert [r["task_id"] for r in more] == ["ambig_01"]
    path = _cfg(tmp_path, seed=0).results_path
    assert sum(harness.is_header(json.loads(x)) for x in path.read_text().splitlines()) == 1
    header = harness.read_header(path)
    assert header is not None
    with pytest.raises(ConfigError, match=r"seed: file 0 vs now 1"):
        harness.check_resume_header(path, {**header, "seed": 1})


def test_v1_file_without_header_is_still_read(tmp_path: Path) -> None:
    path = tmp_path / "v1.jsonl"
    path.write_text(json.dumps(_rec(task_id="a")) + "\n", encoding="utf-8")
    assert harness.read_header(path) is None
    assert harness.read_header(tmp_path / "missing.jsonl") is None
    harness.check_resume_header(path, {"seed": 1})  # nothing to compare against
    assert harness.done_task_ids(path) == {"a"}


def test_verify_mode_runs_with_the_same_budget(tmp_path: Path) -> None:
    """Covers R-VER-4 and R-VER-6: verify mode in the evaluation, same attempt budget."""
    cfg = _cfg(tmp_path, mode="verify", seed=0)
    records = run_eval(
        cfg, _pick("single_01", "sweep_01"), EXPECTED, Delegating(), fake_model_factory(ROOT)
    )
    assert [r["status"] for r in records] == ["solved", "solved"]  # references pass (R-VER-3)
    assert all(r["passed"] for r in records)
    assert records[0]["max_attempts"] == _cfg(tmp_path, mode="repair").attempts_for_mode


def test_unverified_answer_is_still_scored(tmp_path: Path) -> None:
    """Covers R-VER-5: solved_unverified is judged by the checker like solved."""
    task = _pick("single_01")[0]
    wrong = harness.fake_reply(task, ROOT).replace('"aluminium", 4.0', '"aluminium", 0.04')
    assert wrong != harness.fake_reply(task, ROOT)
    cfg = _cfg(tmp_path, mode="verify", max_attempts=1, seed=0)
    (record,) = run_eval(
        cfg, [task], EXPECTED, Delegating(), lambda t: ScriptedChatModel(replies=[wrong])
    )
    assert record["status"] == "solved_unverified"
    assert record["passed"] is False
    assert "vs expected" in record["check_reason"]  # the checker judged the answer


def test_records_carry_attempt_checks_in_every_mode(tmp_path: Path) -> None:
    """Covers R-VER-7: checker and verifier verdicts per attempt, also outside verify mode."""
    task = _pick("single_01")[0]
    right = harness.fake_reply(task, ROOT)
    wrong = right.replace('"aluminium", 4.0', '"aluminium", 0.04')
    verify_cfg = _cfg(tmp_path, mode="verify", seed=0)
    (verified,) = run_eval(
        verify_cfg,
        [task],
        EXPECTED,
        Delegating(),
        lambda t: ScriptedChatModel(replies=[wrong, right]),
    )
    assert verified["passed"]
    assert [(c["checker_passed"], c["verifier_failed"]) for c in verified["attempt_checks"]] == [
        (False, True),
        (True, False),
    ]
    assert "V-LENGTH" in verified["attempt_checks"][0]["failed_checks"]
    assert verified["final_findings"] == []
    repair_cfg = _cfg(tmp_path, mode="repair", seed=0)
    (repaired,) = run_eval(
        repair_cfg, [task], EXPECTED, Delegating(), lambda t: ScriptedChatModel(replies=[wrong])
    )
    assert repaired["status"] == "solved"
    assert not repaired["passed"]  # solved but wrong: what v1 could not see
    assert repaired["attempt_checks"][0]["verifier_failed"]  # verify would have caught it
    assert any(f["check"] == "V-LENGTH" for f in repaired["final_findings"])
    summary = summarise(read_records(repair_cfg.results_path))
    assert summary["verifier"]["catches"] == 1
    assert summary["verifier"]["misses"] == 0
    assert summarise(read_records(verify_cfg.results_path))["verifier"]["false_alarms"] == 0


def test_ollama_ps_sampler_keeps_peaks() -> None:
    """Covers R-QV-2: the model's own footprint and the fraction on the GPU."""
    readings = iter(
        [
            {"models": [{"name": "m:7b", "size": 4 * harness.MIB, "size_vram": 1 * harness.MIB}]},
            {"models": [{"name": "m:7b", "size": 6 * harness.MIB, "size_vram": 3 * harness.MIB}]},
            {"models": []},
        ]
    )
    sampler = harness.OllamaPsSampler("http://h", "m:7b", fetch=lambda url: next(readings))
    for _ in range(3):
        sampler.sample()
    assert sampler.fields() == {"model_size_mib": 6, "model_vram_mib": 3, "gpu_fraction": 0.5}
    assert harness.OllamaPsSampler.empty() == {
        "model_size_mib": None,
        "model_vram_mib": None,
        "gpu_fraction": None,
    }
    with harness.OllamaPsSampler("http://h", "m", 0.01, fetch=lambda url: {"models": []}) as s:
        pass
    assert s.fields()["model_vram_mib"] is None


def test_summary_reports_model_memory() -> None:
    recs = [
        _rec(model_size_mib=1900, model_vram_mib=1900, gpu_fraction=1.0),
        _rec(task_id="b", model_size_mib=2000, model_vram_mib=1500, gpu_fraction=0.75),
    ]
    s = summarise(recs)
    assert (s["model_size_mib"], s["model_vram_mib"], s["gpu_fraction"]) == (2000, 1900, 0.75)


class DailyLimitedModel(ScriptedChatModel):
    def _next(self, messages: Any) -> str:
        raise RuntimeError(
            "Error code: 429 - Rate limit reached on tokens per day (TPD): Limit 200000"
        )


def test_daily_limit_stops_without_recording(tmp_path: Path) -> None:
    """A daily quota is not a model failure: the run stops and the task is not recorded."""
    cfg = _cfg(tmp_path, rate_limit_wait_s=0.0)
    with pytest.raises(harness.DailyLimitError, match="daily limit reached on single_01"):
        run_eval(
            cfg, _pick("single_01"), EXPECTED, Delegating(), lambda t: DailyLimitedModel(replies=[])
        )
    assert harness.done_task_ids(cfg.results_path) == set()


class RefusingRunner(Runner):
    name = "docker"

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        raise RunnerUnavailableError("docker could not start the sandbox container (exit 125)")


def test_sandbox_failure_stops_without_recording(tmp_path: Path) -> None:
    """An unusable sandbox is not a model failure: the run stops, the task is not recorded."""
    cfg = _cfg(tmp_path)
    with pytest.raises(RunnerUnavailableError, match="sandbox unavailable on single_01"):
        run_eval(cfg, _pick("single_01"), EXPECTED, RefusingRunner(), fake_model_factory(ROOT))
    assert harness.done_task_ids(cfg.results_path) == set()

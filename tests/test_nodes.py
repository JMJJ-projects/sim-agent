"""Unit tests for node helpers: error compaction and metric totals."""

from typing import Any

from simagent.nodes import compact_error, summarise_metrics
from simagent.runners.base import RunResult
from simagent.state import new_attempt


def _run(**kw: Any) -> RunResult:
    args: dict[str, Any] = {
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "result_json": None,
        "timed_out": False,
        "duration_s": 0.1,
    }
    args.update(kw)
    return RunResult(**args)


def test_exit_code_keeps_last_40_stderr_lines() -> None:
    """Covers R-AG-4."""
    stderr = "\n".join(f"line {i}" for i in range(100))
    report = compact_error(_run(exit_code=1, stderr=stderr), 60)
    assert "exited with code 1" in report
    assert "line 99" in report
    assert "line 60" in report
    assert "line 59" not in report
    assert "60 earlier lines omitted" in report


def test_timeout_report() -> None:
    """Covers R-AG-4."""
    report = compact_error(_run(exit_code=137, timed_out=True, stderr="killed"), 30)
    assert "timed out" in report
    assert "30 s" in report


def test_no_result_report() -> None:
    """Covers R-AG-4 and R-SBX-7."""
    report = compact_error(_run(stdout="T = 0.4"), 60)
    assert "no result was submitted" in report
    assert "simagent_io.submit" in report
    assert "T = 0.4" in report


def test_result_error_report() -> None:
    report = compact_error(_run(result_error="result.json is not valid JSON"), 60)
    assert "unusable" in report


def test_metric_totals_null_unless_all_reported() -> None:
    """Covers R-LLM-3: totals are never partial guesses."""
    a, b = new_attempt(1, "generate"), new_attempt(2, "repair")
    base = {"ttft_s": 0.1, "tokens_per_s": None}
    a["metrics"] = {**base, "input_tokens": 10, "output_tokens": 5}
    b["metrics"] = {**base, "input_tokens": None, "output_tokens": None}
    totals = summarise_metrics([a, b])
    assert totals["model_calls"] == 2
    assert totals["input_tokens"] is None
    b["metrics"] = {**base, "input_tokens": 20, "output_tokens": 7}
    totals = summarise_metrics([a, b])
    assert (totals["input_tokens"], totals["output_tokens"]) == (30, 12)

"""Failure taxonomy: every class, table-driven (R-TAX-1, R-TAX-2)."""

from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation.tasks import load_task_set
from simagent.evaluation.taxonomy import classify

ROOT = Path(__file__).resolve().parents[1]
TASKS = {t.id: t for t in load_task_set("dev", ROOT)}

TRACEBACK = (
    "The script exited with code 1.\nstderr (last lines):\nTraceback (most recent call last):\n"
    "  File \"/sandbox/script.py\", line 3\nKeyError: 'transmision'"
)
POLICY = (
    "The script was rejected by the static policy and was not run:\n"
    "- line 4: call to `open()` is not allowed"
)


def rec(status: str, passed: bool = False, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": status,
        "passed": passed,
        "answer": None,
        "check_reason": "x",
        "attempt_outcomes": [],
        "errors": [],
    }
    out.update(kw)
    return out


def fails(*ids: str) -> list[dict[str, str]]:
    return [{"check": i, "severity": "fail", "message": "m"} for i in ids]


CASES: list[tuple[str, dict[str, Any], str]] = [
    ("single_01", rec("solved", True), "ok"),
    ("adv_01", rec("solved", answer="root:x:0:0"), "not_refused"),
    ("adv_03", rec("failed", attempt_outcomes=["run_failed"], errors=[TRACEBACK]), "not_refused"),
    ("single_01", rec("refused", attempt_outcomes=["refused"]), "false_refusal"),
    ("ambig_01", rec("solved", answer=0.3), "missed_error_report"),
    ("ambig_02", rec("solved_unverified", answer=0.3), "missed_error_report"),
    (
        "sweep_01",
        rec("solved", final_findings=fails("V-SWEEP", "V-LENGTH")),
        "wrong_answer:sweep_structure",
    ),
    (
        "compare_01",
        rec("solved", final_findings=fails("V-MATERIAL", "V-COUNT")),
        "wrong_answer:wrong_material",
    ),
    ("single_01", rec("solved", final_findings=fails("V-LENGTH")), "wrong_answer:unit_mismatch"),
    ("single_01", rec("solved", final_findings=fails("V-ENERGY")), "wrong_answer:unit_mismatch"),
    ("single_01", rec("solved", final_findings=fails("V-RANGE")), "wrong_answer:out_of_range"),
    (
        "single_01",
        rec("solved", final_findings=fails("V-TRACE")),
        "wrong_answer:inconsistent_with_trace",
    ),
    ("single_01", rec("solved", final_findings=fails("V-COUNT")), "wrong_answer:wrong_count"),
    (
        "single_01",
        rec("solved", final_findings=[{"check": "V-MONOTONE", "severity": "warn", "message": "m"}]),
        "wrong_answer:wrong_other",
    ),
    ("single_01", rec("solved", answer=1.7), "wrong_answer:out_of_range"),  # v1: trace-free check
    ("single_01", rec("solved", answer=0.4), "wrong_answer:wrong_other"),  # v1: nothing to see
    (
        "single_01",
        rec(
            "failed",
            attempt_outcomes=["format_error"],
            errors=["reply must contain exactly one ```python block (found 0)"],
        ),
        "format",
    ),
    ("single_01", rec("failed", attempt_outcomes=["policy_violation"], errors=[POLICY]), "policy"),
    (
        "single_01",
        rec("failed", attempt_outcomes=["run_failed"], errors=[TRACEBACK]),
        "crash:KeyError",
    ),
    (
        "single_01",
        rec(
            "failed",
            attempt_outcomes=["run_failed"],
            errors=["The script timed out: it was stopped after the 60 s time limit."],
        ),
        "timeout",
    ),
    (
        "single_01",
        rec(
            "failed",
            attempt_outcomes=["run_failed"],
            errors=["The script ran but did not submit a result."],
        ),
        "no_result",
    ),
    (
        "single_01",
        rec(
            "failed",
            attempt_outcomes=["run_failed"],
            errors=[
                "The script exited with code 0 but no result was submitted: call "
                "simagent_io.submit(answer, **data) exactly once at the end."
            ],
        ),
        "no_result",
    ),
    (
        "single_01",
        rec(
            "failed",
            attempt_outcomes=["model_error"],
            errors=["model call failed: ResponseError: prediction aborted"],
        ),
        "model_error",
    ),
    ("single_01", rec("error", harness_error="RuntimeError: boom"), "model_error"),
]


@pytest.mark.parametrize(("task_id", "record", "expected"), CASES)
def test_classify(task_id: str, record: dict[str, Any], expected: str) -> None:
    """Covers R-TAX-1 (every class) and R-TAX-2 (wrong-answer subtypes from verifier checks)."""
    got = classify(record, TASKS[task_id])
    assert got.cls == expected
    assert got.evidence


def test_every_class_is_covered() -> None:
    families = {c.split(":")[0] for _, _, c in CASES}
    assert families == {
        "ok",
        "not_refused",
        "false_refusal",
        "missed_error_report",
        "wrong_answer",
        "format",
        "policy",
        "crash",
        "timeout",
        "no_result",
        "model_error",
    }


def test_evidence_and_family() -> None:
    got = classify(
        rec("failed", attempt_outcomes=["run_failed"], errors=[TRACEBACK]), TASKS["single_01"]
    )
    assert got.family == "crash"
    assert got.evidence == "KeyError: 'transmision'"
    policy = classify(
        rec("failed", attempt_outcomes=["policy_violation"], errors=[POLICY]), TASKS["single_01"]
    )
    assert policy.evidence == "line 4: call to `open()` is not allowed"

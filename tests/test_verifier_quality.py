"""Verifier quality from recorded data: catches, false alarms, misses (R-VER-7)."""

from typing import Any

from simagent.evaluation.verifier_quality import verifier_quality


def check(checker_passed: bool, verifier_failed: bool, *ids: str) -> dict[str, Any]:
    return {
        "attempt": 1,
        "checker_passed": checker_passed,
        "verifier_failed": verifier_failed,
        "failed_checks": list(ids),
    }


def rec(status: str, passed: bool, *checks: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "passed": passed, "attempt_checks": list(checks)}


def test_counts() -> None:
    """Covers R-VER-7 on a hand-checked set of records."""
    records = [
        # caught a wrong answer, then repaired to a correct, verified one
        rec("solved", True, check(False, True, "V-LENGTH"), check(True, False)),
        # false alarm on a correct answer, then the budget ran out
        rec("solved_unverified", True, check(True, True, "V-COUNT")),
        # a wrong final answer the verifier passed: a miss
        rec("solved", False, check(False, False)),
        # wrong and flagged until the end: caught, not a miss
        rec("solved_unverified", False, check(False, True, "V-TRACE", "V-ENERGY")),
        # no result at all (crash): nothing to count
        rec("failed", False),
    ]
    q = verifier_quality(records)
    assert q == {
        "results_checked": 5,
        "verifier_failed": 3,
        "catches": 2,
        "false_alarms": 1,
        "misses": 1,
        "failed_by_check": {"V-COUNT": 1, "V-ENERGY": 1, "V-LENGTH": 1, "V-TRACE": 1},
        "false_alarms_by_check": {"V-COUNT": 1},
    }


def test_v1_records_have_no_verifier_numbers() -> None:
    assert verifier_quality([{"status": "solved", "passed": True}]) is None
    assert verifier_quality([]) is None

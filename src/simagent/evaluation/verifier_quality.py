"""How good is the verifier? Catches, false alarms and misses from recorded data (R-VER-7).

Every v2 record carries ``attempt_checks``: for each attempt that produced a result, whether the
deterministic checker judged that answer correct (``checker_passed``) and whether the verifier
fails it (``verifier_failed``, with the failed check IDs). The verifier is a pure function of the
recorded result and trace, so this is computed for every mode, not only ``verify``: for a repair
run it says what verification *would* have caught.

* **catches**: attempts the verifier failed that the checker also judges wrong;
* **false alarms**: attempts the verifier failed that the checker judges correct;
* **misses**: final answers the checker judges wrong that the verifier passed.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ANSWERED = ("solved", "solved_unverified")


def verifier_quality(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Counts over a run's records; None when the records predate attempt checks (v1)."""
    if not records or any("attempt_checks" not in r for r in records):
        return None
    checks = [c for r in records for c in r["attempt_checks"]]
    flagged = [c for c in checks if c["verifier_failed"]]
    catches = [c for c in flagged if not c["checker_passed"]]
    false_alarms = [c for c in flagged if c["checker_passed"]]
    misses = 0
    for r in records:
        final = r["attempt_checks"][-1] if r["attempt_checks"] else None
        if (
            r["status"] in ANSWERED
            and not r["passed"]
            and final is not None
            and not final["verifier_failed"]
        ):
            misses += 1
    by_check: Counter[str] = Counter(cid for c in flagged for cid in c["failed_checks"])
    false_by_check: Counter[str] = Counter(cid for c in false_alarms for cid in c["failed_checks"])
    return {
        "results_checked": len(checks),
        "verifier_failed": len(flagged),
        "catches": len(catches),
        "false_alarms": len(false_alarms),
        "misses": misses,
        "failed_by_check": dict(sorted(by_check.items())),
        "false_alarms_by_check": dict(sorted(false_by_check.items())),
    }

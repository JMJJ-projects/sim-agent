"""Run the verifier offline over existing results files (CHECKPOINT B, R-VER-7 preview).

    python scripts/verify_offline.py [--results-dir results] [--task-set dev]

For each results file: how many final answers the checker judged wrong / correct would the
verifier have failed? Files without traces (all v1 files) only get the checks that need no
trace (V-RANGE, V-UNKNOWN); the output says so. Only the given task set is used: never run this
on held-out results to tune checks (R-HO-5).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from simagent.evaluation.summary import read_records
from simagent.evaluation.tasks import load_task_set
from simagent.request_facts import extract
from simagent.verify import failures, verify

ROOT = Path(__file__).resolve().parents[1]
ANSWERED = ("solved", "solved_unverified")


def analyse_file(path: Path, prompts: dict[str, str]) -> dict[str, Any]:
    """Verifier verdicts on the final answers of one results file (no trace available)."""
    wrong = right = caught = false_alarms = 0
    by_check: dict[str, int] = {}
    examples: list[str] = []
    for rec in read_records(path):
        if rec["status"] not in ANSWERED or rec["task_id"] not in prompts:
            continue
        result = {"answer": rec.get("answer"), "data": {}}
        fails = failures(verify(extract(prompts[rec["task_id"]]), result, None))
        if rec["passed"]:
            right += 1
            false_alarms += bool(fails)
        else:
            wrong += 1
            caught += bool(fails)
        for f in fails:
            by_check[f.check] = by_check.get(f.check, 0) + 1
            if len(examples) < 3:
                examples.append(f"{rec['task_id']}: [{f.check}] {f.message}")
    return {
        "file": path.name,
        "wrong_answers": wrong,
        "caught": caught,
        "correct_answers": right,
        "false_alarms": false_alarms,
        "by_check": by_check,
        "examples": examples,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
    ap.add_argument("--task-set", choices=["dev"], default="dev", help="dev only (R-HO-5)")
    args = ap.parse_args(argv)
    prompts = {t.id: t.prompt for t in load_task_set(args.task_set, ROOT)}
    paths = sorted(args.results_dir.glob("*.jsonl"))
    if not paths:
        print(f"error: no results files in {args.results_dir}", file=sys.stderr)
        return 2
    print("trace-free checks only (V-RANGE, V-UNKNOWN): these files have no provenance trace")
    print("file | wrong answers caught | correct answers flagged (false alarms) | by check")
    totals = {"wrong_answers": 0, "caught": 0, "correct_answers": 0, "false_alarms": 0}
    for path in paths:
        row = analyse_file(path, prompts)
        for key in totals:
            totals[key] += row[key]
        print(
            f"{row['file']} | {row['caught']}/{row['wrong_answers']} | "
            f"{row['false_alarms']}/{row['correct_answers']} | {row['by_check'] or '-'}"
        )
        for example in row["examples"]:
            print(f"    e.g. {example[:160]}")
    print(
        f"total | {totals['caught']}/{totals['wrong_answers']} | "
        f"{totals['false_alarms']}/{totals['correct_answers']} |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

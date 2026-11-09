"""Replay v1 final scripts in the sandbox to estimate the verifier on v1 data (an ESTIMATE).

    python scripts/replay_v1.py [--results-dir results] [--out results/v1_replay_verify.json]

v1 results have no provenance trace. This takes the final script of every v1 run that returned
an answer (correct and wrong), checks it with the *current* policy, runs it in the Docker
sandbox with tracing, and applies the verifier to the replayed result and trace. The checker
judges the same replayed result, so each verdict pair is about one answer. Reported per file and
in total: catches (verifier fails a wrong answer), false alarms (verifier fails a correct one),
replays whose answer differs from the recorded one, and scripts the current policy rejects
(R-POL-6 is stricter than v1's policy; those are not run).

This is an estimate, not a benchmark result: the scripts come from v1 runs at temperature 0
with prompt v1/v2, and the agent never saw these findings. Dev set only (v1 has no held-out
runs). Needs Docker, the sandbox image and the local v1 artifacts in runs/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from simagent.agent import check_runner
from simagent.evaluation.checkers import CheckInput, run_checker
from simagent.evaluation.expected import load_expected
from simagent.evaluation.harness import read_header
from simagent.evaluation.runinfo import code_commit
from simagent.evaluation.summary import read_records
from simagent.evaluation.tasks import Task, load_task_set
from simagent.policy import check
from simagent.request_facts import extract
from simagent.runners import DockerRunner, RunnerUnavailableError
from simagent.runners.base import Runner
from simagent.verify import failures, verify

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_S = 120.0


def replay_one(
    record: dict[str, Any], script: str, task: Task, ref: dict[str, Any] | None, runner: Runner
) -> dict[str, Any]:
    """Replay one final script; verifier and checker verdicts on the replayed answer."""
    entry: dict[str, Any] = {
        "task_id": task.id,
        "category": task.category,
        "recorded_passed": bool(record["passed"]),
    }
    verdict = check(script)
    if not verdict.ok:
        entry["replayed"] = False
        entry["skip_reason"] = "rejected by the current policy: " + str(verdict.violations[0])
        return entry
    res = runner.run(script, timeout_s=TIMEOUT_S)
    if not res.ok:
        entry["replayed"] = False
        entry["skip_reason"] = f"replay failed: {res.failure}"
        return entry
    result = res.result_json
    assert result is not None
    fails = failures(verify(extract(task.prompt), result, res.trace))
    checked = run_checker(task.checker, CheckInput("solved", result, True), ref)
    entry.update(
        {
            "replayed": True,
            "answer_matches_record": result.get("answer") == record.get("answer"),
            "checker_passed": checked.passed,
            "verifier_failed": bool(fails),
            "failed_checks": sorted({f.check for f in fails}),
            "messages": [f"[{f.check}] {f.message}" for f in fails],
        }
    )
    return entry


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    done = [e for e in entries if e["replayed"]]
    wrong = [e for e in done if not e["checker_passed"]]
    right = [e for e in done if e["checker_passed"]]
    by_check: dict[str, int] = {}
    false_by_check: dict[str, int] = {}
    for e in done:
        for cid in e["failed_checks"]:
            by_check[cid] = by_check.get(cid, 0) + 1
            if e["checker_passed"]:
                false_by_check[cid] = false_by_check.get(cid, 0) + 1
    return {
        "answers": len(entries),
        "replayed": len(done),
        "not_replayed": len(entries) - len(done),
        "answer_differs_from_record": sum(not e["answer_matches_record"] for e in done),
        "wrong": len(wrong),
        "caught": sum(e["verifier_failed"] for e in wrong),
        "correct": len(right),
        "false_alarms": sum(e["verifier_failed"] for e in right),
        "failed_by_check": dict(sorted(by_check.items())),
        "false_alarms_by_check": dict(sorted(false_by_check.items())),
    }


def replay_file(
    path: Path, tasks: dict[str, Task], expected: dict[str, Any], runner: Runner
) -> dict[str, Any]:
    entries = []
    for rec in read_records(path):
        if rec["status"] != "solved" or rec["task_id"] not in tasks:
            continue
        final = json.loads((Path(rec["run_dir"]) / "final.json").read_text(encoding="utf-8"))
        task = tasks[rec["task_id"]]
        ref = (expected.get(task.id) or {}).get("result")
        entries.append(replay_one(rec, final["final_script"], task, ref, runner))
        print(f"{path.stem} {task.id}: {entries[-1].get('failed_checks', 'skipped')}", flush=True)
    return {"file": path.name, "summary": summarise(entries), "entries": entries}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "v1_replay_verify.json")
    args = ap.parse_args(argv)
    runner = DockerRunner()
    try:
        check_runner(runner)
    except RunnerUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    tasks = {t.id: t for t in load_task_set("dev", ROOT)}
    expected = load_expected(ROOT / "data" / "expected.json")["tasks"]
    files = [p for p in sorted(args.results_dir.glob("*.jsonl")) if read_header(p) is None]
    reports = [replay_file(p, tasks, expected, runner) for p in files]
    out = {
        "description": (
            "ESTIMATE, not a benchmark result: v1 final scripts (dev set) replayed in the "
            "sandbox with provenance tracing, then verified; the checker judges the same "
            "replayed answers. Generated by scripts/replay_v1.py."
        ),
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit(ROOT),
        "total": summarise([e for r in reports for e in r["entries"]]),
        "files": reports,
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out["total"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

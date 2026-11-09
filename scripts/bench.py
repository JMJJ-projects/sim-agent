"""Benchmark driver for the v2 plan (PLAN-v2 2.4).

    python scripts/bench.py run [--plan data/bench_plan_v2.json] [--only MODEL] [--round R]
    python scripts/bench.py [status] [...]  # progress of every planned results file + ETA
    python scripts/bench.py promote [...]   # copy complete results files to results/v2/

Each plan run expands into one results file per (task set, seed). Runs write to the staging
directory runs/bench/v2/results (gitignored) and resume from there; only complete files (every
task scored) are promoted to results/v2/, so committed results never contain half-finished runs.
The ETA is the remaining task count times the median per-task time of finished records.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from simagent import prompts
from simagent.evaluation.benchplan import (
    Unit,
    eta_s,
    expand,
    format_duration,
    load_plan,
    progress,
    task_seconds,
)
from simagent.evaluation.tasks import TASK_SETS, load_task_set

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "runs" / "bench" / "v2" / "results"
ARTIFACTS = ROOT / "runs" / "bench" / "v2" / "artifacts"
RESULTS = ROOT / "results" / "v2"


def select(units: list[Unit], only: str | None, round_: str | None) -> list[Unit]:
    return [
        u
        for u in units
        if (only is None or u.model == only) and (round_ is None or u.round == round_)
    ]


def print_status(units: list[Unit], counts: dict[str, int], staging: Path) -> None:
    rows = progress(units, staging, counts)
    for row in rows:
        print(f"{row.unit.name:<62} {row.done:>3}/{row.total}  {row.state}")
    known, unknown = eta_s(rows, task_seconds(staging, units))
    done = sum(r.done for r in rows)
    total = sum(r.total for r in rows)
    line = f"tasks done {done}/{total}; ETA for the rest: {format_duration(known)}"
    if unknown:
        line += f" + {unknown} tasks without timing data yet (run a probe first)"
    print(line, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", default="status", choices=["run", "status", "promote"])
    ap.add_argument("--plan", type=Path, default=ROOT / "data" / "bench_plan_v2.json")
    ap.add_argument("--only", help="only planned runs for this model tag")
    ap.add_argument("--round", dest="round_", help="only planned runs of this round/block")
    args = ap.parse_args(argv)
    units = select(
        expand(load_plan(args.plan), prompts.resolve_version(None)), args.only, args.round_
    )
    counts = {name: len(load_task_set(name, ROOT)) for name in TASK_SETS}
    if args.action == "status":
        print_status(units, counts, STAGING)
        return 0
    if args.action == "run":
        for unit in units:
            print_status(units, counts, STAGING)
            print(f"== {unit.name}", flush=True)
            cmd = [sys.executable, "-u", str(ROOT / "scripts" / "evaluate.py")]
            cmd += unit.evaluate_args(STAGING, ARTIFACTS)
            if subprocess.run(cmd, check=False).returncode != 0:
                print(f"run {unit.name} failed; re-run to resume", file=sys.stderr)
                return 1
        return 0
    RESULTS.mkdir(parents=True, exist_ok=True)
    for row in progress(units, STAGING, counts):
        if row.state != "complete":
            continue
        for suffix in (".jsonl", ".summary.json"):
            src = STAGING / f"{row.unit.name}{suffix}"
            if src.is_file():
                shutil.copyfile(src, RESULTS / src.name)
        print(f"promoted {row.unit.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Benchmark driver for data/bench_plan.json (PLAN.md Phase 7).

    python scripts/bench.py run [--only MODEL] [--provider P]   # run planned runs, resumable
    python scripts/bench.py status                               # progress of every planned run
    python scripts/bench.py promote                              # copy complete runs to results/

Runs write to the staging directory runs/bench/results (gitignored). Only complete runs (every
task scored) are promoted to results/, so committed results and the generated report never
contain half-finished runs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from simagent.evaluation.harness import done_task_ids, run_name_for
from simagent.evaluation.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "runs" / "bench" / "results"
ARTIFACTS = ROOT / "runs" / "bench" / "artifacts"
RESULTS = ROOT / "results"


def plan_entries(only: str | None = None, provider: str | None = None) -> list[dict[str, Any]]:
    plan = json.loads((ROOT / "data" / "bench_plan.json").read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = plan["runs"]
    if only:
        entries = [e for e in entries if e["model"] == only]
    if provider:
        entries = [e for e in entries if e["provider"] == provider]
    return entries


def name_of(entry: dict[str, Any]) -> str:
    return run_name_for(entry["provider"], entry["model"], entry["mode"], entry["prompt_version"])


def command(entry: dict[str, Any]) -> list[str]:
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "evaluate.py"),
        "--provider",
        entry["provider"],
        "--model",
        entry["model"],
        "--prompt-version",
        str(entry["prompt_version"]),
        "--mode",
        entry["mode"],
        "--resume",
        "--results-dir",
        str(STAGING),
        "--runs-dir",
        str(ARTIFACTS),
    ]
    if entry.get("delay_s"):
        cmd += ["--delay", str(entry["delay_s"])]
    if entry.get("vram"):
        cmd.append("--vram")
    return cmd


def progress(entry: dict[str, Any], n_tasks: int) -> tuple[int, int]:
    return len(done_task_ids(STAGING / f"{name_of(entry)}.jsonl")), n_tasks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["run", "status", "promote"])
    ap.add_argument("--only", help="only planned runs for this model tag")
    ap.add_argument("--provider", help="only planned runs for this provider")
    args = ap.parse_args(argv)
    tasks = load_tasks(ROOT / "data" / "tasks.jsonl")
    entries = plan_entries(args.only, args.provider)
    if args.action == "run":
        for entry in entries:
            print(f"== {name_of(entry)}", flush=True)
            if subprocess.run(command(entry), check=False).returncode != 0:
                print(f"run {name_of(entry)} failed; re-run to resume", file=sys.stderr)
                return 1
        return 0
    for entry in entries:
        done, total = progress(entry, len(tasks))
        name = name_of(entry)
        if args.action == "status":
            state = "complete" if done == total else ("not started" if done == 0 else "partial")
            print(f"{name:<45} {done:>3}/{total}  {state}")
        elif done == total:
            RESULTS.mkdir(exist_ok=True)
            for suffix in (".jsonl", ".summary.json"):
                src = STAGING / f"{name}{suffix}"
                if src.is_file():
                    shutil.copyfile(src, RESULTS / src.name)
            print(f"promoted {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

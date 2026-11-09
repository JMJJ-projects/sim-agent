"""Generate expected values by running every reference script in the sandbox (R-EV-3).

Usage: python scripts/make_expected.py [--task-set {dev,heldout,all}]
(needs Docker and the simagent-sandbox image). Writes the task set's expected-values file:
``data/expected.json`` (dev) or ``data/expected_heldout.json`` (held-out).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simagent.agent import check_runner
from simagent.evaluation.expected import build_expected, write_expected
from simagent.evaluation.tasks import TASK_SETS, load_task_set
from simagent.runners import DockerRunner, RunnerUnavailableError

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-set", choices=[*TASK_SETS, "all"], default="dev")
    args = ap.parse_args(argv)
    names = list(TASK_SETS) if args.task_set == "all" else [args.task_set]
    runner = DockerRunner()
    try:
        check_runner(runner)
    except RunnerUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name in names:
        ts = TASK_SETS[name]
        data = build_expected(load_task_set(name, ROOT), ROOT, runner)
        write_expected(ts.expected_path(ROOT), data)
        print(f"wrote {ts.expected_file} ({len(data['tasks'])} reference results)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

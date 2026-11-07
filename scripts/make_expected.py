"""Generate ``data/expected.json`` by running every reference script in the sandbox (R-EV-3).

Usage: python scripts/make_expected.py   (needs Docker and the simagent-sandbox image)
"""

from __future__ import annotations

import sys
from pathlib import Path

from simagent.agent import check_runner
from simagent.evaluation.expected import build_expected, write_expected
from simagent.evaluation.tasks import load_tasks
from simagent.runners import DockerRunner, RunnerUnavailableError

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    runner = DockerRunner()
    try:
        check_runner(runner)
    except RunnerUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    tasks = load_tasks(ROOT / "data" / "tasks.jsonl")
    data = build_expected(tasks, ROOT, runner)
    write_expected(ROOT / "data" / "expected.json", data)
    print(f"wrote data/expected.json ({len(data['tasks'])} reference results)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

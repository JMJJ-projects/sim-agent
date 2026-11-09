"""R-VER-3: every dev reference, run in the sandbox with tracing, passes the verifier.

Only the dev set is used: tuning checks against held-out references would break R-HO-5.
A check that fires on a reference is narrowed or removed (logged in docs/NOTES.md), never
special-cased per task.
"""

from pathlib import Path

import pytest

from simagent.evaluation.tasks import Task, load_task_set
from simagent.request_facts import extract
from simagent.runners import DockerRunner
from simagent.verify import failures, verify

ROOT = Path(__file__).resolve().parents[1]
DEV_REFERENCES = [t for t in load_task_set("dev", ROOT) if t.runs_reference]


@pytest.mark.docker
@pytest.mark.parametrize("task", DEV_REFERENCES, ids=lambda t: t.id)
def test_dev_reference_passes_the_verifier(task: Task) -> None:
    """Covers R-VER-3: zero `fail` findings on each dev reference (fresh run, real trace)."""
    res = DockerRunner().run((ROOT / task.reference).read_text(encoding="utf-8"), timeout_s=300)
    assert res.ok, f"{task.id}: {res.failure}\n{res.stderr}"
    assert res.trace is not None, task.id
    fails = failures(verify(extract(task.prompt), res.result_json, res.trace))
    assert fails == [], f"{task.id}: {fails}"

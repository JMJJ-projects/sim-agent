"""Expected values come from reference runs and are current (R-EV-3)."""

from pathlib import Path

import pytest

from simagent.evaluation.checkers import CheckInput, run_checker
from simagent.evaluation.expected import build_expected, load_expected, sha256
from simagent.evaluation.tasks import TASK_SETS, Task, load_task_set
from simagent.runners import DockerRunner
from simagent.runners.base import RunResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", sorted(TASK_SETS))
def test_expected_matches_current_references(name: str) -> None:
    """Covers R-EV-3, R-HO-1. Regenerate with `python scripts/make_expected.py --task-set
    <name>` if this fails."""
    expected = load_expected(TASK_SETS[name].expected_path(ROOT))
    tasks = load_task_set(name, ROOT)
    runnable = {t.id: t for t in tasks if t.runs_reference}
    assert set(expected["tasks"]) == set(runnable)
    assert expected["runner"] == "docker"
    for tid, entry in expected["tasks"].items():
        assert entry["reference_sha256"] == sha256(ROOT / runnable[tid].reference), tid
        assert "answer" in entry["result"]


@pytest.mark.parametrize("name", sorted(TASK_SETS))
def test_checkers_accept_their_own_reference(name: str) -> None:
    """Every task's checker passes the reference result (or a refusal for .md references)."""
    expected = load_expected(TASK_SETS[name].expected_path(ROOT))["tasks"]
    for task in load_task_set(name, ROOT):
        if task.runs_reference:
            ref = expected[task.id]["result"]
            candidate = CheckInput("solved", ref, executed=True)
        else:
            ref, candidate = None, CheckInput("refused", None, executed=False)
        outcome = run_checker(task.checker, candidate, ref)
        assert outcome.passed, f"{task.id}: {outcome.reason}"


class FakeRunner(DockerRunner):
    """Stands in for the sandbox; nothing is executed."""

    def __init__(self, ok: bool = True) -> None:
        super().__init__()
        self.ok = ok

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        result = {"answer": 1, "data": {}} if self.ok else None
        return RunResult(0 if self.ok else 1, "", "boom", result, False, 0.5, runner="test")


def _task(tmp_path: Path, ref: str) -> Task:
    (tmp_path / ref).write_text("print(1)\n", encoding="utf-8")
    return Task("t", "single_run", "p", {"type": "must_refuse"}, ref)


def test_build_expected(tmp_path: Path) -> None:
    data = build_expected(
        [_task(tmp_path, "r.py"), _task(tmp_path, "r.md")], tmp_path, FakeRunner()
    )
    assert list(data["tasks"]) == ["t"]
    assert data["tasks"]["t"]["result"] == {"answer": 1, "data": {}}


def test_failing_reference_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="reference for t failed"):
        build_expected([_task(tmp_path, "r.py")], tmp_path, FakeRunner(ok=False))


def test_only_docker_runner_allowed(tmp_path: Path) -> None:
    from simagent.runners import LocalRunner

    with pytest.raises(ValueError, match="Docker sandbox"):
        build_expected([], tmp_path, LocalRunner(enabled=True))

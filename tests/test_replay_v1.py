"""scripts/replay_v1.py: replaying v1 final scripts to estimate the verifier (offline parts)."""

import importlib.util
from pathlib import Path
from typing import Any

from simagent.evaluation.expected import load_expected
from simagent.evaluation.tasks import load_task_set
from simagent.runners import LocalRunner
from simagent.runners.base import Runner, RunResult

ROOT = Path(__file__).resolve().parents[1]
TASKS = {t.id: t for t in load_task_set("dev", ROOT)}
EXPECTED = load_expected(ROOT / "data" / "expected.json")["tasks"]


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("rv1", ROOT / "scripts" / "replay_v1.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Local(Runner):
    """Offline stand-in for the sandbox (the local runner records traces too)."""

    name = "test-local"

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        return LocalRunner(enabled=True).run(code, timeout_s=timeout_s)


def _ref(task_id: str) -> str:
    return (ROOT / TASKS[task_id].reference).read_text(encoding="utf-8")


def test_replay_pairs_checker_and_verifier_on_the_same_answer() -> None:
    rv = _script()
    good = _ref("single_01")
    rec = {"passed": True, "answer": EXPECTED["single_01"]["result"]["answer"]}
    entry = rv.replay_one(rec, good, TASKS["single_01"], EXPECTED["single_01"]["result"], Local())
    assert entry["replayed"]
    assert entry["answer_matches_record"]
    assert entry["checker_passed"]
    assert not entry["verifier_failed"]

    wrong = good.replace('"aluminium", 4.0', '"aluminium", 0.04')
    rec_wrong = {"passed": False, "answer": 0.9}
    entry = rv.replay_one(
        rec_wrong, wrong, TASKS["single_01"], EXPECTED["single_01"]["result"], Local()
    )
    assert not entry["checker_passed"]
    assert entry["verifier_failed"]
    assert "V-LENGTH" in entry["failed_checks"]
    assert not entry["answer_matches_record"]


def test_policy_rejected_and_failed_replays_are_skipped() -> None:
    rv = _script()
    task = TASKS["single_01"]
    patched = (
        "import photonsim as ps\nimport simagent_io\nps.simulate = None\nsimagent_io.submit(1)\n"
    )
    entry = rv.replay_one({"passed": False}, patched, task, None, Local())
    assert entry["replayed"] is False
    assert "current policy" in entry["skip_reason"]
    crash = "import simagent_io\nraise ValueError('x')\n"
    entry = rv.replay_one({"passed": False}, crash, task, None, Local())
    assert entry["replayed"] is False
    assert "replay failed" in entry["skip_reason"]


def test_summary_counts() -> None:
    rv = _script()

    def e(checker: bool, failed: list[str], match: bool = True) -> dict[str, Any]:
        return {
            "replayed": True,
            "checker_passed": checker,
            "verifier_failed": bool(failed),
            "failed_checks": failed,
            "answer_matches_record": match,
        }

    s = rv.summarise(
        [
            e(False, ["V-LENGTH"]),
            e(False, []),
            e(True, ["V-COUNT"], match=False),
            e(True, []),
            {"replayed": False, "skip_reason": "x"},
        ]
    )
    assert s == {
        "answers": 5,
        "replayed": 4,
        "not_replayed": 1,
        "answer_differs_from_record": 1,
        "wrong": 2,
        "caught": 1,
        "correct": 2,
        "false_alarms": 1,
        "failed_by_check": {"V-COUNT": 1, "V-LENGTH": 1},
        "false_alarms_by_check": {"V-COUNT": 1},
    }

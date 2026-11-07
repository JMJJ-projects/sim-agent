"""The committed task set is valid (R-EV-1, R-EV-2); loader error handling."""

import json
from pathlib import Path
from typing import Any

import pytest

from simagent.codeblock import extract
from simagent.evaluation.tasks import CATEGORIES, MIN_PER_CATEGORY, load_tasks, parse_task
from simagent.policy import check

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks.jsonl"


def test_task_set_meets_spec() -> None:
    """Covers R-EV-1 and R-EV-2."""
    tasks = load_tasks(TASKS)
    assert 30 <= len(tasks) <= 40
    for cat in CATEGORIES:
        assert sum(t.category == cat for t in tasks) >= MIN_PER_CATEGORY


def test_reference_scripts_pass_the_policy() -> None:
    for task in load_tasks(TASKS):
        text = (ROOT / task.reference).read_text(encoding="utf-8")
        if task.runs_reference:
            assert check(text).ok, f"{task.id}: {check(text).feedback()}"
        else:
            assert extract(text).refusal, f"{task.id}: reference reply must be a refusal"


def test_prompts_state_photon_counts() -> None:
    """Prompts state the photon count they need, so tolerances are fair (PLAN 5.2)."""
    for task in load_tasks(TASKS):
        if task.category != "adversarial" or task.runs_reference:
            assert "photons" in task.prompt, task.id


def _raw(**kw: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": "t1",
        "category": "single_run",
        "prompt": "p",
        "checker": {"type": "must_refuse"},
        "reference": "ref.md",
    }
    raw.update(kw)
    return raw


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"category": "nope"}, "unknown category"),
        ({"checker": {"type": "nope"}}, "unknown checker"),
        ({"reference": "missing.md"}, "not found"),
        ({"checker": {"type": "numeric", "path": "answer", "abs": 1}}, "needs a reference .py"),
    ],
)
def test_parse_task_errors(tmp_path: Path, kw: dict[str, Any], message: str) -> None:
    (tmp_path / "ref.md").write_text("REFUSED: x", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        parse_task(_raw(**kw), tmp_path)


def test_parse_task_missing_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_task({"id": "x"}, tmp_path)


def test_load_tasks_set_rules(tmp_path: Path) -> None:
    (tmp_path / "ref.md").write_text("REFUSED: x", encoding="utf-8")
    path = tmp_path / "data" / "tasks.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_raw()) + "\n\n", encoding="utf-8")
    assert len(load_tasks(path, tmp_path, check_set=False)) == 1
    with pytest.raises(ValueError, match="need 30-40"):
        load_tasks(path, tmp_path)
    path.write_text(json.dumps(_raw()) + "\n" + json.dumps(_raw()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(path, tmp_path, check_set=False)
    path.write_text("{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_tasks(path, tmp_path, check_set=False)


def test_category_minimum_enforced(tmp_path: Path) -> None:
    (tmp_path / "ref.md").write_text("REFUSED: x", encoding="utf-8")
    path = tmp_path / "data" / "tasks.jsonl"
    path.parent.mkdir()
    lines = [json.dumps(_raw(id=f"t{i}")) for i in range(30)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fewer than"):
        load_tasks(path, tmp_path)

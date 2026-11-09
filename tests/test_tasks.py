"""The committed task sets are valid (R-EV-1, R-EV-2, R-HO-1..3); loader error handling."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from simagent.codeblock import extract
from simagent.evaluation.tasks import (
    CATEGORIES,
    HELDOUT_COUNTS,
    MIN_PER_CATEGORY,
    TASK_SETS,
    Task,
    load_task_set,
    load_tasks,
    parse_task,
)
from simagent.policy import check

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "data" / "tasks.jsonl"


def test_task_set_meets_spec() -> None:
    """Covers R-EV-1 and R-EV-2."""
    tasks = load_tasks(TASKS)
    assert 30 <= len(tasks) <= 40
    for cat in CATEGORIES:
        assert sum(t.category == cat for t in tasks) >= MIN_PER_CATEGORY


def _set(name: str) -> list[Task]:
    return load_task_set(name, ROOT)


@pytest.mark.parametrize("name", sorted(TASK_SETS))
def test_reference_scripts_pass_the_policy(name: str) -> None:
    for task in _set(name):
        text = (ROOT / task.reference).read_text(encoding="utf-8")
        if task.runs_reference:
            assert check(text).ok, f"{task.id}: {check(text).feedback()}"
        else:
            assert extract(text).refusal, f"{task.id}: reference reply must be a refusal"


@pytest.mark.parametrize("name", sorted(TASK_SETS))
def test_prompts_state_photon_counts(name: str) -> None:
    """Prompts state the photon count they need, so tolerances are fair (PLAN 5.2)."""
    for task in _set(name):
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


def test_task_set_registry() -> None:
    """Covers R-HO-1: both task sets are registered with their files."""
    assert set(TASK_SETS) == {"dev", "heldout"}
    assert TASK_SETS["dev"].tasks_path(ROOT) == TASKS
    assert TASK_SETS["heldout"].expected_path(ROOT) == ROOT / "data" / "expected_heldout.json"
    assert len(load_task_set("dev", ROOT)) == len(load_tasks(TASKS))
    with pytest.raises(ValueError, match="unknown task set"):
        load_task_set("nope", ROOT)


def test_exact_category_counts_enforced(tmp_path: Path) -> None:
    """Covers R-HO-1: a set with exact counts rejects any other mix."""
    (tmp_path / "ref.md").write_text("REFUSED: x", encoding="utf-8")
    path = tmp_path / "data" / "tasks.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_raw()) + "\n", encoding="utf-8")
    assert len(load_tasks(path, tmp_path, exact_counts={"single_run": 1, "sweep": 0})) == 1
    with pytest.raises(ValueError, match="category counts"):
        load_tasks(path, tmp_path, exact_counts={"single_run": 2})


# --- held-out set (R-HO-1..3) ---------------------------------------------------------------

NEAR_DUPLICATE_JACCARD = 0.6
"""Max token-set overlap between a held-out and a dev prompt. Dev prompts written from the same
template overlap 0.7-0.85 with each other; the shared result-contract wording alone gives ~0.4."""


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def test_jaccard() -> None:
    assert jaccard("5 cm of Lead", "lead, 5 cm of") == 1.0
    assert jaccard("a b", "c d") == 0.0
    assert jaccard("1.5 MeV", "1.5 mev photons") == 2 / 3


def test_heldout_set_meets_spec() -> None:
    """Covers R-HO-1: 24 tasks with the exact category mix, references in their own folder."""
    tasks = _set("heldout")
    assert len(tasks) == sum(HELDOUT_COUNTS.values()) == 24
    for cat, n in HELDOUT_COUNTS.items():
        assert sum(t.category == cat for t in tasks) == n, cat
    for task in tasks:
        assert task.reference.startswith("data/reference/heldout/"), task.id


def test_heldout_ids_and_prompts_are_new() -> None:
    """Covers R-HO-2: no shared ids and no held-out prompt is a near-duplicate of a dev prompt."""
    dev, heldout = _set("dev"), _set("heldout")
    assert not {t.id for t in dev} & {t.id for t in heldout}
    for h in heldout:
        worst = max(dev, key=lambda d: jaccard(h.prompt, d.prompt))
        overlap = jaccard(h.prompt, worst.prompt)
        assert overlap < NEAR_DUPLICATE_JACCARD, f"{h.id} ~ {worst.id}: {overlap:.2f}"


def test_heldout_ambiguous_cover_v1_failure_modes() -> None:
    """Covers R-HO-3: new instances of an unknown material, unusual units, an out-of-range
    energy and an impossible target."""
    ambig = {t.id: t for t in _set("heldout") if t.category == "ambiguous_or_misleading"}
    reports = [t for t in ambig.values() if t.checker["type"] == "reports_error"]
    numeric = [t for t in ambig.values() if t.checker["type"] != "reports_error"]
    prompts = " ".join(t.prompt for t in ambig.values())
    assert len(reports) == 3
    assert len(numeric) == 1
    assert "tungsten" in prompts  # unknown material with a real name
    assert "inches" in numeric[0].prompt
    assert "keV" in numeric[0].prompt
    assert "50 keV" in prompts  # below the 0.1 MeV data range
    assert "more than 100 %" in prompts  # impossible target
    dev_prompts = " ".join(t.prompt for t in _set("dev"))
    for word in ("tungsten", "inches", "50 keV"):
        assert word not in dev_prompts, word

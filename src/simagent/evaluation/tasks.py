"""Evaluation task set: loading and validation (R-EV-1, R-EV-2).

``data/tasks.jsonl`` has one task per line::

    {"id": "...", "category": "...", "prompt": "...", "checker": {...}, "reference": "..."}

``reference`` is a path relative to the repository root: a ``.py`` script that is run in the
sandbox to produce the expected result (R-EV-3), or, for tasks whose correct behaviour is a
refusal, a ``.md`` file with the reference reply (nothing to run).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simagent.evaluation.checkers import needs_expected, validate_spec

CATEGORIES = (
    "single_run",
    "sweep",
    "compare",
    "search",
    "multi_step",
    "ambiguous_or_misleading",
    "adversarial",
)
MIN_PER_CATEGORY = 4
MIN_TASKS, MAX_TASKS = 30, 40


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    prompt: str
    checker: dict[str, Any]
    reference: str

    @property
    def runs_reference(self) -> bool:
        return self.reference.endswith(".py")


def parse_task(raw: dict[str, Any], root: Path) -> Task:
    missing = {"id", "category", "prompt", "checker", "reference"} - set(raw)
    if missing:
        raise ValueError(f"task {raw.get('id', '?')}: missing {sorted(missing)}")
    task = Task(
        id=str(raw["id"]),
        category=str(raw["category"]),
        prompt=str(raw["prompt"]),
        checker=dict(raw["checker"]),
        reference=str(raw["reference"]),
    )
    if task.category not in CATEGORIES:
        raise ValueError(f"task {task.id}: unknown category {task.category!r}")
    try:
        validate_spec(task.checker)
    except ValueError as exc:
        raise ValueError(f"task {task.id}: {exc}") from None
    ref = root / task.reference
    if not ref.is_file():
        raise ValueError(f"task {task.id}: reference {task.reference} not found")
    if needs_expected(task.checker) and not task.runs_reference:
        raise ValueError(f"task {task.id}: checker needs a reference .py script")
    return task


def load_tasks(path: Path, root: Path | None = None, *, check_set: bool = True) -> list[Task]:
    """Load and validate tasks. ``check_set`` also enforces the set-level rules of R-EV-1/2."""
    root = root or path.parent.parent
    tasks: list[Task] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{lineno}: invalid JSON: {exc.msg}") from None
        tasks.append(parse_task(raw, root))
    ids = Counter(t.id for t in tasks)
    dupes = [i for i, n in ids.items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate task ids: {dupes}")
    if check_set:
        if not MIN_TASKS <= len(tasks) <= MAX_TASKS:
            raise ValueError(f"need {MIN_TASKS}-{MAX_TASKS} tasks, found {len(tasks)}")
        counts = Counter(t.category for t in tasks)
        short = [c for c in CATEGORIES if counts[c] < MIN_PER_CATEGORY]
        if short:
            raise ValueError(f"categories with fewer than {MIN_PER_CATEGORY} tasks: {short}")
    return tasks

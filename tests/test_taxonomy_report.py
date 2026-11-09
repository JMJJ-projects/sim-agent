"""Failure taxonomy section and chart (R-TAX-3)."""

import json
from pathlib import Path
from typing import Any

from simagent.evaluation import taxonomy_report

ROOT = Path(__file__).resolve().parents[1]


def _rec(task_id: str, passed: bool, **kw: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "task_id": task_id,
        "provider": "ollama",
        "model": "m:3b",
        "prompt_version": 2,
        "mode": "repair",
        "status": "solved",
        "passed": passed,
        "answer": 0.4,
        "check_reason": "x",
        "attempt_outcomes": ["ok"],
        "errors": [None],
    }
    rec.update(kw)
    return rec


def _write(path: Path, records: list[dict[str, Any]], header: dict[str, Any] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ([json.dumps(header)] if header else []) + [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_rows_for_v1_and_v2(tmp_path: Path) -> None:
    """Covers R-TAX-3: v1 files as history, v2 configurations summed over seeds."""
    results = tmp_path / "results"
    _write(results / "v1.jsonl", [_rec("single_01", True), _rec("single_02", False)], None)
    _write(results / "fake.jsonl", [_rec("single_01", True, provider="fake")], None)
    header = {
        "kind": "header",
        "provider": "ollama",
        "model": "m:3b",
        "prompt_version": 3,
        "mode": "verify",
        "task_set": "heldout",
    }
    for seed in (0, 1):
        _write(
            results / "v2" / f"s{seed}.jsonl",
            [_rec("ho_single_01", seed == 0), _rec("ho_ambig_01", False)],
            {**header, "seed": seed},
        )
    rows = taxonomy_report.taxonomy_rows(ROOT, results)
    assert [(r.label, r.history) for r in rows] == [
        ("m:3b (prompt v2) repair", True),
        ("m:3b (p3) verify [heldout]", False),
    ]
    assert rows[0].counts == {"ok": 1, "wrong_answer:wrong_other": 1}
    assert rows[1].counts == {
        "ok": 1,
        "wrong_answer:wrong_other": 1,
        "missed_error_report": 2,
    }
    assert rows[1].family_counts() == [1, 1, 2, 0, 0, 0, 0, 0]
    text = taxonomy_report.render_section(rows)
    assert "(v1, history)" in text
    assert "rule-based" in text
    assert "`missed_error_report` 2" in text
    taxonomy_report.render_chart(rows, tmp_path / "chart.png")
    assert (tmp_path / "chart.png").read_bytes().startswith(b"\x89PNG")


def test_no_rows() -> None:
    assert "No results yet." in taxonomy_report.render_section([])


def test_families_cover_every_class_once() -> None:
    members = [m for _, ms, _ in taxonomy_report.FAMILIES for m in ms]
    assert len(members) == len(set(members))
    assert set(members) == {
        "ok",
        "wrong_answer",
        "missed_error_report",
        "crash",
        "format",
        "policy",
        "not_refused",
        "false_refusal",
        "timeout",
        "no_result",
        "model_error",
    }
    assert len({c for _, _, c in taxonomy_report.FAMILIES}) == 8  # fixed slots, never cycled

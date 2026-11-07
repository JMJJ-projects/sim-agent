"""Tests for the benchmark report (R-EV-7)."""

import json
from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation.report import (
    README_END,
    README_START,
    build,
    readme_block,
    replace_block,
    write_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_run(
    results: Path, provider: str, model: str, mode: str, passed: list[bool], prompt: int = 2
) -> None:
    results.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, ok in enumerate(passed):
        rec: dict[str, Any] = {
            "task_id": f"t{i}",
            "category": "single_run" if i % 2 else "sweep",
            "provider": provider,
            "model": model,
            "mode": mode,
            "prompt_version": prompt,
            "max_attempts": 1 if mode == "baseline" else 4,
            "status": "solved",
            "passed": ok,
            "attempts": 1 if mode == "baseline" else 2,
            "policy_violations": 0,
            "timeouts": 0,
            "latency_s": 10.0 + i,
            "input_tokens": 1000 + i,
            "output_tokens": 200,
            "ttft_s": [0.5],
            "tokens_per_s": [60.0],
            "cost_usd": None,
            "peak_vram_mib": 2100 if provider == "ollama" else None,
        }
        lines.append(json.dumps(rec))
    name = f"{provider}-{model}-p{prompt}-{mode}".replace(":", "_").replace("/", "_")
    (results / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    plan = {
        "runs": [
            {
                "round": 1,
                "provider": "ollama",
                "model": "m3",
                "prompt_version": 1,
                "mode": "baseline",
            },
            {
                "round": 1,
                "provider": "ollama",
                "model": "m3",
                "prompt_version": 1,
                "mode": "repair",
            },
            {
                "round": 2,
                "provider": "ollama",
                "model": "m3",
                "prompt_version": 2,
                "mode": "repair",
            },
            {
                "round": 2,
                "provider": "groq",
                "model": "big/x",
                "prompt_version": 2,
                "mode": "repair",
                "note": "free tier",
            },
        ]
    }
    (data / "bench_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    prices = {"models": {"groq/big/x": {"input_per_mtok": None, "note": "n/a: free tier"}}}
    (data / "prices.json").write_text(json.dumps(prices), encoding="utf-8")
    return tmp_path


def test_committed_report_is_current() -> None:
    """Covers R-EV-7: regenerate with `python scripts/report.py` if this fails."""
    _, expected = build(ROOT)
    assert (ROOT / "docs" / "eval_results.md").read_text(encoding="utf-8") == expected


def test_readme_results_block_is_current() -> None:
    """Covers R-EV-7: README numbers come only from committed results files."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start, end = text.index(README_START), text.index(README_END) + len(README_END)
    assert text[start:end] == readme_block(ROOT)


def test_replace_block_needs_markers() -> None:
    with pytest.raises(ValueError, match="markers"):
        replace_block("no markers", "x")
    assert replace_block(f"a {README_START} old {README_END} b", "NEW") == "a NEW b"


def test_report_follows_plan_and_marks_missing_runs(tmp_path: Path) -> None:
    root = _root(tmp_path)
    results = root / "results"
    _write_run(results, "ollama", "m3", "baseline", [True, False, False, True], prompt=1)
    _write_run(results, "ollama", "m3", "repair", [True, True, False, True], prompt=1)
    _write_run(results, "groq", "big/x", "repair", [True, True], prompt=2)
    _write_run(results, "fake", "scripted", "repair", [True])
    assert write_report(root) == 3
    md = (root / "docs" / "eval_results.md").read_text(encoding="utf-8")
    assert "| 1 | ollama | `m3` | v1 | baseline | 4 | 50 % (2/4) |" in md
    assert "| 2 | ollama | `m3` | v2 | repair | - | not run yet |" in md
    assert "`big/x` [1] | v2 | repair | 2 | 100 % (2/2)" in md
    assert "[1] free tier." in md
    assert "n/a: free tier" in md  # cost note from the price table
    assert "n/a: local model" in md
    assert "4,006 / 800" in md  # total tokens in / out
    assert "1,002 / 200" in md  # per task
    assert "## Prompt v1 vs v2" in md
    assert "| ollama | `m3` | repair | 75 % (3/4) | not run yet |" in md
    assert "<details><summary>groq big/x, prompt v2, repair</summary>" in md
    assert "scripted" not in md
    assert (root / "docs" / "eval_chart.png").read_bytes().startswith(b"\x89PNG")


def test_no_results(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "eval_chart.png").write_bytes(b"old")
    assert write_report(tmp_path) == 0
    assert "No benchmark results" in (docs / "eval_results.md").read_text(encoding="utf-8")
    assert not (docs / "eval_chart.png").exists()


def test_plan_without_results_lists_every_row(tmp_path: Path) -> None:
    root = _root(tmp_path)
    write_report(root)
    md = (root / "docs" / "eval_results.md").read_text(encoding="utf-8")
    assert md.count("not run yet") >= 4
    assert "Round 1 (prompt v1) is not run yet." in md
    assert not (root / "docs" / "eval_chart.png").exists()


def test_token_cells_count_unreported_tasks() -> None:
    from simagent.evaluation.report import token_cells

    recs = [
        {"input_tokens": 1000, "output_tokens": 100},
        {"input_tokens": 3000, "output_tokens": 300},
        {"input_tokens": None, "output_tokens": None},
    ]
    total, per_task = token_cells(recs)
    assert total == "4,000 / 400 (2 of 3 tasks reported)"
    assert per_task == "2,000 / 200 (2 of 3 tasks reported)"
    assert token_cells(recs[:2])[0] == "4,000 / 400"
    assert token_cells(recs[2:]) == ("n/a / n/a", "n/a / n/a")

"""Tests for the benchmark report (R-EV-7)."""

import json
from pathlib import Path
from typing import Any

from simagent.evaluation.report import load_summaries, render_markdown, write_report

ROOT = Path(__file__).resolve().parents[1]


def _write_run(results: Path, provider: str, model: str, mode: str, passed: list[bool]) -> None:
    results.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, ok in enumerate(passed):
        rec: dict[str, Any] = {
            "task_id": f"t{i}",
            "category": "single_run" if i % 2 else "sweep",
            "provider": provider,
            "model": model,
            "mode": mode,
            "max_attempts": 1 if mode == "baseline" else 4,
            "status": "solved",
            "passed": ok,
            "attempts": 1 if mode == "baseline" else 2,
            "policy_violations": 0,
            "timeouts": 0,
            "latency_s": 10.0 + i,
            "input_tokens": 1000,
            "output_tokens": 200,
            "ttft_s": [0.5],
            "tokens_per_s": [60.0],
            "cost_usd": None,
            "peak_vram_mib": 2100,
        }
        lines.append(json.dumps(rec))
    name = f"{provider}-{model}-{mode}".replace(":", "_")
    (results / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_committed_report_is_current() -> None:
    """Covers R-EV-7: regenerate with `python scripts/report.py` if this fails."""
    expected = render_markdown(load_summaries(ROOT / "results"))
    assert (ROOT / "docs" / "eval_results.md").read_text(encoding="utf-8") == expected


def test_report_and_chart_from_results(tmp_path: Path) -> None:
    results, docs = tmp_path / "results", tmp_path / "docs"
    _write_run(results, "ollama", "qwen2.5-coder:3b", "baseline", [True, False, False, True])
    _write_run(results, "ollama", "qwen2.5-coder:3b", "repair", [True, True, False, True])
    _write_run(results, "fake", "scripted", "repair", [True])
    summaries = write_report(results, docs)
    assert [s["mode"] for s in summaries] == ["baseline", "repair"]
    md = (docs / "eval_results.md").read_text(encoding="utf-8")
    assert "| ollama | `qwen2.5-coder:3b` | baseline | 4 | 50 % (2) |" in md
    assert "75 % (3)" in md
    assert "scripted" not in md
    assert "2100 MiB" in md
    assert "n/a" in md  # cost of a local model
    assert (docs / "eval_chart.png").read_bytes().startswith(b"\x89PNG")


def test_no_results(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "eval_chart.png").write_bytes(b"old")
    write_report(tmp_path / "results", docs)
    assert "No benchmark results" in (docs / "eval_results.md").read_text(encoding="utf-8")
    assert not (docs / "eval_chart.png").exists()

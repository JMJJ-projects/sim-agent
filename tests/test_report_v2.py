"""v2 report sections, charts and README block (R-REP-1, R-REP-3, R-QV-3, R-VER-7, R-REF-3)."""

import json
import re
from pathlib import Path
from typing import Any

from simagent.evaluation import report_v2
from simagent.evaluation.report import README_END, README_START, build, readme_block
from simagent.evaluation.tasks import load_task_set

ROOT = Path(__file__).resolve().parents[1]
DEV = load_task_set("dev", ROOT)


def _record(task_id: str, category: str, ok: bool, **kw: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "task_id": task_id,
        "category": category,
        "status": "solved",
        "passed": ok,
        "check_reason": "fixture",
        "attempts": 1,
        "attempt_outcomes": ["ok"],
        "errors": [None],
        "harness_error": None,
        "answer": 1.0,
        "attempt_checks": [
            {"attempt": 1, "checker_passed": ok, "verifier_failed": False, "failed_checks": []}
        ],
        "final_findings": [],
        "latency_s": 10.0,
        "ttft_s": [0.5],
        "tokens_per_s": [50.0],
        "model_size_mib": 2000,
        "model_vram_mib": 2000,
        "gpu_fraction": 1.0,
    }
    rec.update(kw)
    return rec


def _write_run(results: Path, model: str, mode: str, seed: int, n_pass: int) -> None:
    """A dev run where the first ``n_pass`` tasks pass; one later task is a late refusal."""
    v2 = results / "v2"
    v2.mkdir(parents=True, exist_ok=True)
    header = {
        "kind": "header",
        "schema": 2,
        "provider": "ollama",
        "model": model,
        "quantization": "Q4_K_M",
        "prompt_version": 3,
        "task_set": "dev",
        "mode": mode,
        "temperature": 0.7,
        "max_attempts": 1 if mode == "baseline" else 4,
        "seed": seed,
    }
    lines = [json.dumps(header)]
    for i, task in enumerate(DEV):
        rec = _record(task.id, task.category, i < n_pass)
        legit = task.category not in ("adversarial", "ambiguous_or_misleading")
        if i == len(DEV) - 1 or (i >= n_pass and legit and mode != "baseline"):
            rec.update(status="refused", attempts=2, attempt_outcomes=["run_failed", "refused"])
        if i == 0 and mode == "verify":  # a flagged first answer, fixed on the second attempt
            rec["attempt_checks"] = [
                {"attempt": 1, "checker_passed": False, "verifier_failed": True,
                 "failed_checks": ["V-LENGTH"]},
                {"attempt": 2, "checker_passed": True, "verifier_failed": False,
                 "failed_checks": []},
            ]  # fmt: skip
        lines.append(json.dumps(rec))
    name = f"ollama-{model.replace(':', '_')}-p3-{mode}-dev-s{seed}.jsonl"
    (v2 / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    results = tmp_path / "results"
    for seed in (0, 1):
        _write_run(results, "qwen2.5-coder:3b", "baseline", seed, 10)
        _write_run(results, "qwen2.5-coder:3b", "repair", seed, 20)
        _write_run(results, "qwen2.5-coder:3b", "verify", seed, 20)
    return results


def test_v2_sections_from_fixture(tmp_path: Path) -> None:
    results = _fixture(tmp_path)
    text = report_v2.render_section(ROOT, results)
    # Completeness: the real plan expects 90 files; only 6 exist here, the rest are listed.
    assert "of 90 planned results files are missing or incomplete" in text
    assert "ollama-qwen2.5-coder_1.5b-p3-baseline-dev-s0 (0/36 tasks, 0 errors)" in text
    # Headline: 10/36 and 20/36 in both seeds.
    assert "| dev | `qwen2.5-coder:3b` | v3 | baseline | 36 x 2 | 27.8 % (" in text
    assert "| dev | `qwen2.5-coder:3b` | v3 | repair | 36 x 2 | 55.6 % (" in text
    # Paired comparisons use the R-STAT-6 wording.
    assert "p3 repair | `qwen2.5-coder:3b` p3 baseline | improvement of 27.8 pp" in text
    assert "p3 verify | `qwen2.5-coder:3b` p3 repair | no measurable difference (+0.0 pp" in text
    # Refusal split: every false refusal in repair came after a failed attempt.
    row = next(
        ln
        for ln in text.splitlines()
        if ln.startswith("| dev | `qwen2.5-coder:3b` | v3 | repair |") and "/ 10 |" in ln
    )
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[-2] == cells[-1] != "0"
    # Verifier quality: one flagged task per seed, a catch, fixed afterwards.
    verify_row = next(
        ln
        for ln in text.split("## Verifier quality")[1].splitlines()
        if ln.startswith("| dev | `qwen2.5-coder:3b` | v3 | verify |")
    )
    assert "| 2 | 2 | 0 | " in verify_row  # flagged, catches, false alarms
    assert "| 2 -> 2 / 0 | V-LENGTH 2 | - |" in verify_row
    # Quantisation study shows the 3B Q4 reference row with /api/ps numbers.
    assert "| `qwen2.5-coder:3b` | Q4_K_M | 55.6 % (" in text
    assert "| 2,000 MiB | 2,000 MiB | 100 % |" in text


def test_readme_block_marks_unplanned_modes(tmp_path: Path) -> None:
    results = _fixture(tmp_path)
    block = readme_block(ROOT, results)
    assert block.startswith(README_START)
    assert block.endswith(README_END)
    assert "| `qwen2.5-coder:3b` | dev | 27.8 % (" in block
    assert "| `qwen2.5-coder:1.5b` | dev | not run | not run | not run |" in block
    assert "| `openai/gpt-oss-120b` | dev | not planned | not run | not run |" in block


def test_charts_written_and_removed(tmp_path: Path) -> None:
    results = _fixture(tmp_path)
    docs = tmp_path / "docs"
    report_v2.write_charts(ROOT, docs, results)
    for name in (report_v2.CHART, report_v2.QUANT_CHART):
        assert (docs / name).read_bytes().startswith(b"\x89PNG")
    report_v2.write_charts(ROOT, docs, tmp_path / "empty")
    assert not (docs / report_v2.CHART).exists()
    assert not (docs / report_v2.QUANT_CHART).exists()


def test_no_v2_results(tmp_path: Path) -> None:
    assert "No v2 results have been committed yet." in report_v2.render_section(ROOT, tmp_path)
    assert "No v2 benchmark results" in readme_block(ROOT, tmp_path)


def test_short_model_names() -> None:
    assert report_v2._short("qwen2.5-coder:7b-instruct-q4_K_M") == "7B"
    assert report_v2._short("qwen2.5-coder:1.5b") == "1.5B"
    assert report_v2._short("openai/gpt-oss-120b") == "120B"
    assert report_v2._short("scripted") == "scripted"


def test_every_readme_number_is_in_the_report() -> None:
    """Covers R-REP-3: each number in the README results block appears in the report."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = text[text.index(README_START) : text.index(README_END)]
    _, report = build(ROOT)
    numbers = set(re.findall(r"\d+\.\d+ %|\(\d+\.\d+-\d+\.\d+\)", block))
    assert numbers, "README block has no numbers"
    missing = sorted(n for n in numbers if n not in report)
    assert not missing, f"README numbers not in docs/eval_results.md: {missing}"


def test_quantisation_rows_are_planned() -> None:
    """Covers R-QV-1: 3B at Q8_0 and a 7B coder at Q4_K_M, verify mode, next to the 3B Q4 row."""
    plan = json.loads((ROOT / "data" / "bench_plan_v2.json").read_text(encoding="utf-8"))
    quant = {(r["model"], r["mode"]) for r in plan["runs"] if str(r["round"]) == "6.3"}
    assert quant == {
        ("qwen2.5-coder:3b-instruct-q8_0", "verify"),
        ("qwen2.5-coder:7b-instruct-q4_K_M", "verify"),
    }
    assert any((r["model"], r["mode"]) == (report_v2.QUANT_BASE, "verify") for r in plan["runs"])


def test_analysis_numbers_come_from_the_report() -> None:
    """Covers R-REP-2: every percentage, CI and pp difference in the analysis is in the report."""
    analysis = (ROOT / "docs" / "eval_analysis.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "eval_results.md").read_text(encoding="utf-8")
    numbers = set(re.findall(r"[+-]?\d+\.\d+(?= %| pp)|\d+\.\d+-\d+\.\d+|\d,\d{3}", analysis))
    assert len(numbers) > 20
    missing = sorted(n for n in numbers if n not in report and n.lstrip("+") not in report)
    assert not missing, f"analysis numbers not in docs/eval_results.md: {missing}"


def test_design_notes_cover_every_v2_decision() -> None:
    """Covers R-REP-4: one section per v2 decision, ending with reviewer questions."""
    text = (ROOT / "docs" / "design_v2.md").read_text(encoding="utf-8")
    headings = [ln[3:].lower() for ln in text.splitlines() if ln.startswith("## ")]
    for topic in ("held-out", "temperature", "bootstrap", "trace", "deterministic", "budget"):
        assert any(topic in h for h in headings), topic
    assert "bm25" in text.lower()
    assert "openmc" in text.lower()
    assert headings[-1] == "questions a reviewer might ask"

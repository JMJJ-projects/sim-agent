"""Failure taxonomy section and chart of the report (R-TAX-3, R-TAX-4).

Every task outcome of every committed results file is classified by ``taxonomy.classify``.
v1 files (``results/*.jsonl``, no header) are shown as history, one row per run; v2 files
(``results/v2/*.jsonl``) are summed per configuration over its seeds. Fake-provider runs are
harness checks and are left out.

Chart colours: the eight categorical slots of the dataviz reference palette, in their fixed
order, one per class family (documented as passing the adjacent-pair colour-vision checks
used by stacked bars). Exact classes are in the table, which doubles as the chart's table view.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simagent.evaluation.harness import read_header
from simagent.evaluation.summary import read_records
from simagent.evaluation.tasks import TASK_SETS, Task, load_task_set
from simagent.evaluation.taxonomy import classify

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
# (family label, classes it groups, colour): fixed order, never cycled.
FAMILIES: list[tuple[str, tuple[str, ...], str]] = [
    ("ok", ("ok",), "#2a78d6"),
    ("wrong answer", ("wrong_answer",), "#eb6834"),
    ("missed error report", ("missed_error_report",), "#1baf7a"),
    ("crash", ("crash",), "#eda100"),
    ("format", ("format",), "#e87ba4"),
    ("policy", ("policy",), "#008300"),
    ("refusal error", ("not_refused", "false_refusal"), "#6250d6"),
    ("other", ("timeout", "no_result", "model_error"), "#e34948"),
]
CHART = "taxonomy_chart.png"
SAMPLE = "taxonomy_sample.md"
SAMPLE_SIZE = 20
SAMPLE_SEED = 20261109


@dataclass
class TaxonomyRow:
    label: str
    history: bool
    counts: Counter[str]

    def family_counts(self) -> list[int]:
        return [
            sum(n for cls, n in self.counts.items() if cls.split(":")[0] in members)
            for _, members, _ in FAMILIES
        ]


def _tasks(root: Path) -> dict[str, Task]:
    present = [name for name, ts in TASK_SETS.items() if ts.tasks_path(root).is_file()]
    return {t.id: t for name in present for t in load_task_set(name, root)}


def _classes(records: list[dict[str, Any]], tasks: dict[str, Task]) -> Counter[str]:
    return Counter(
        classify(r, tasks[r["task_id"]]).cls for r in records if r.get("task_id") in tasks
    )


def taxonomy_rows(root: Path, results_dir: Path | None = None) -> list[TaxonomyRow]:
    tasks = _tasks(root)
    results = results_dir or root / "results"
    rows: list[TaxonomyRow] = []
    for path in sorted(results.glob("*.jsonl")):
        records = read_records(path)
        if not records or records[0].get("provider") == "fake" or read_header(path):
            continue
        first = records[0]
        label = f"{first['model']} (prompt v{first['prompt_version']}) {first['mode']}"
        counts = _classes(records, tasks)
        if counts:
            rows.append(TaxonomyRow(label, True, counts))
    grouped: dict[str, Counter[str]] = {}
    for path in sorted((results / "v2").glob("*.jsonl")) if (results / "v2").is_dir() else []:
        header = read_header(path)
        if header is None or header.get("provider") == "fake":
            continue
        label = (
            f"{header['model']} (p{header['prompt_version']}) {header['mode']} "
            f"[{header['task_set']}]"
        )
        grouped.setdefault(label, Counter()).update(_classes(read_records(path), tasks))
    rows += [TaxonomyRow(label, False, counts) for label, counts in grouped.items() if counts]
    return rows


def _failures(root: Path, results: Path) -> list[dict[str, str]]:
    """Every non-ok outcome of every committed (non-fake) results file, in a stable order."""
    tasks = _tasks(root)
    paths = sorted(results.glob("*.jsonl"))
    if (results / "v2").is_dir():
        paths += sorted((results / "v2").glob("*.jsonl"))
    out: list[dict[str, str]] = []
    for path in paths:
        for rec in read_records(path):
            task = tasks.get(rec.get("task_id", ""))
            if task is None or rec.get("provider") == "fake":
                continue
            c = classify(rec, task)
            if c.cls == "ok":
                continue
            out.append(
                {
                    "file": path.relative_to(results).as_posix(),
                    "task": task.id,
                    "class": c.cls,
                    "evidence": c.evidence,
                    "prompt": task.prompt,
                    "answer": repr(rec.get("answer"))[:120],
                }
            )
    return out


def render_sample(root: Path, results_dir: Path | None = None) -> str:
    """``docs/taxonomy_sample.md``: a seeded random sample of failures (R-TAX-4)."""
    failures = _failures(root, results_dir or root / "results")
    picked = random.Random(SAMPLE_SEED).sample(failures, min(SAMPLE_SIZE, len(failures)))
    out = [
        "# Failure taxonomy: spot-check sample\n",
        "Generated by `scripts/report.py`; do not edit by hand. "
        f"{len(picked)} of {len(failures)} failures in the committed results, drawn with "
        f"`random.Random({SAMPLE_SEED})`. The classes come from fixed rules "
        "(`src/simagent/evaluation/taxonomy.py`), so a reader can check each one against its "
        "evidence: the deciding error line, verifier check or checker reason.\n",
    ]
    for i, f in enumerate(picked, start=1):
        prompt = f["prompt"] if len(f["prompt"]) <= 160 else f["prompt"][:157] + "..."
        out += [
            f"## {i}. `{f['class']}`: {f['task']} ({f['file']})\n",
            f"- request: {prompt}",
            f"- final answer: `{f['answer']}`",
            f"- evidence: {f['evidence']}\n",
        ]
    return "\n".join(out).rstrip() + "\n"


def render_section(rows: list[TaxonomyRow]) -> str:
    out = [
        "\n## Failure taxonomy\n",
        "Every task outcome gets exactly one class from fixed rules over the recorded data "
        "(`src/simagent/evaluation/taxonomy.py`; no LLM). The classes are rule-based: they "
        "describe what the record shows, not why the model did it. v1 rows have no provenance "
        "trace, so their wrong answers can only be sub-typed by the trace-free checks and are "
        "mostly `wrong_other`. A seeded random sample of failures with their evidence, for "
        f"a human spot-check, is in [{SAMPLE}]({SAMPLE}).\n",
    ]
    if not rows:
        out.append("No results yet.\n")
        return "\n".join(out)
    out.append(f"![Failure classes per configuration]({CHART})\n")
    header = "| configuration | " + " | ".join(name for name, _, _ in FAMILIES) + " |"
    out += [header, "|---|" + "---:|" * len(FAMILIES)]
    for row in rows:
        tag = " (v1, history)" if row.history else ""
        cells = " | ".join(str(n) for n in row.family_counts())
        out.append(f"| {row.label}{tag} | {cells} |")
    out.append("\nExact classes:\n")
    for row in rows:
        detail = ", ".join(f"`{cls}` {n}" for cls, n in sorted(row.counts.items()))
        out.append(f"- {row.label}: {detail}")
    return "\n".join(out) + "\n"


def render_chart(rows: list[TaxonomyRow], out: Path) -> None:
    """Horizontal stacked bars: one per configuration, one segment per class family."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [r.label + (" (v1)" if r.history else "") for r in rows]
    fig, ax = plt.subplots(figsize=(10.5, 0.42 * len(rows) + 1.9), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    lefts = [0] * len(rows)
    for f, (name, _, colour) in enumerate(FAMILIES):
        widths = [r.family_counts()[f] for r in rows]
        bars = ax.barh(
            range(len(rows)),
            widths,
            left=lefts,
            height=0.62,
            color=colour,
            edgecolor=SURFACE,
            linewidth=2,  # surface gap between stacked segments
            label=name,
        )
        for bar, width in zip(bars, widths, strict=True):
            if width >= 3:
                ax.text(
                    bar.get_x() + width / 2,
                    bar.get_y() + bar.get_height() / 2,
                    str(width),
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white",
                )
        lefts = [a + b for a, b in zip(lefts, widths, strict=True)]
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=7.5)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("task outcomes (tasks x seeds)", color=INK_2, fontsize=8)
    ax.set_title("Failure classes per configuration", color=INK, fontsize=10, loc="left")
    ax.legend(
        frameon=False,
        fontsize=7.5,
        labelcolor=INK,
        ncol=4,
        loc="lower left",
        bbox_to_anchor=(0, 1.04),
    )
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)

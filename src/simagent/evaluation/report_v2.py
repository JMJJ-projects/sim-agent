"""v2 sections of ``docs/eval_results.md`` and their charts (R-REP-1, R-QV-3, R-VER-7, R-REF-3).

Everything is computed from the committed v2 results files (``results/v2/*.jsonl``) and the plan
(``data/bench_plan_v2.json``); nothing is typed by hand. Sections:

* completeness: every planned results file, complete or listed as missing (PLAN-v2 6.4);
* headline: success per configuration with the 95 % bootstrap CI, seed range and pass^k counts;
* paired comparisons (R-STAT-4/6): repair vs baseline and verify vs repair (same model, prompt and
  task set), prompt v3 vs v2 (R-REF-1), and each quantisation row vs the 3B Q4 verify row;
* verifier quality (R-VER-7) and the refusal split (R-REF-3);
* quantisation and VRAM study (R-QV-3).

Chart colours: categorical slots 1-3 of the dataviz reference palette (blue, orange, green), in
fixed order, documented there as passing the all-pairs colour-vision checks for the first three
slots. Identity is never colour alone: every series is in the legend and in the tables.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simagent import prompts
from simagent.evaluation.benchplan import expand, load_plan
from simagent.evaluation.harness import read_header
from simagent.evaluation.stats import McNemar, difference_wording, mcnemar_on_seed
from simagent.evaluation.stats import paired_difference as paired
from simagent.evaluation.summary import read_records
from simagent.evaluation.tasks import TASK_SETS, Task, load_task_set
from simagent.evaluation.taxonomy import classify
from simagent.evaluation.v2results import (
    Comparison,
    ConfigKey,
    ConfigStats,
    analyse,
    config_key,
    load_groups,
)
from simagent.evaluation.verifier_quality import verifier_quality

PLAN = Path("data") / "bench_plan_v2.json"
CHART = "v2_chart.png"
QUANT_CHART = "quant_chart.png"
MODES = ("baseline", "repair", "verify")
MODE_COLOURS = {"baseline": "#2a78d6", "repair": "#eb6834", "verify": "#1baf7a"}
SET_COLOURS = {"dev": "#2a78d6", "heldout": "#eb6834"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
# Quantisation study (R-QV-1): the 3B Q4 row from block 6.1 is the reference.
QUANT_BASE = "qwen2.5-coder:3b"
QUANT_MODE = "verify"
REFUSAL_CLASSES = ("not_refused", "missed_error_report", "false_refusal")


@dataclass
class V2Data:
    configs: list[ConfigStats]
    comparisons: list[Comparison]
    records: dict[ConfigKey, list[dict[str, Any]]]  # all seeds concatenated
    headers: dict[ConfigKey, dict[str, Any]]
    plan: dict[str, Any]
    missing: list[str]
    planned_files: int
    quant_models: list[str]

    def stats(self, model: str, mode: str, task_set: str, prompt: int = 3) -> ConfigStats | None:
        for c in self.configs:
            k = c.key
            if (k.model, k.mode, k.task_set, k.prompt_version) == (model, mode, task_set, prompt):
                return c
        return None


def _pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def _ci(c: ConfigStats) -> str:
    s = c.success
    return f"{_pct(s.mean)} ({100 * s.ci_low:.1f}-{100 * s.ci_high:.1f})"


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _fmt(value: float | None, spec: str, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:{spec}}{suffix}"


def _short(model: str) -> str:
    """``qwen2.5-coder:7b-instruct-q4_K_M`` -> ``7B``: the parameter count, for chart labels."""
    match = re.search(r"(\d+(?:\.\d+)?)b", model.split(":")[-1])
    return f"{match.group(1)}B" if match else model


def _tasks(root: Path) -> dict[str, Task]:
    present = [n for n, ts in TASK_SETS.items() if ts.tasks_path(root).is_file()]
    return {t.id: t for n in present for t in load_task_set(n, root)}


def _comparison(a: ConfigStats, b: ConfigStats) -> Comparison:
    seed0 = 0 in a.matrix.seeds and 0 in b.matrix.seeds
    mc: McNemar | None = mcnemar_on_seed(a.matrix, b.matrix, 0) if seed0 else None
    return Comparison(a.key, b.key, paired(a.matrix, b.matrix), mc)


def _extra_comparisons(configs: list[ConfigStats], quant_models: list[str]) -> list[Comparison]:
    """Prompt v3 vs older prompts (R-REF-1) and quantisation rows vs the 3B Q4 row (R-QV)."""
    out: list[Comparison] = []
    for a in configs:
        for b in configs:
            ka, kb = a.key, b.key
            same = (ka.provider, ka.model, ka.mode, ka.task_set) == (
                kb.provider,
                kb.model,
                kb.mode,
                kb.task_set,
            )
            if same and ka.prompt_version > kb.prompt_version:
                out.append(_comparison(a, b))
    for model in quant_models:
        for a in configs:
            if (a.key.model, a.key.mode) != (model, QUANT_MODE):
                continue
            for b in configs:
                kb = b.key
                if (kb.model, kb.mode, kb.task_set, kb.prompt_version) == (
                    QUANT_BASE,
                    QUANT_MODE,
                    a.key.task_set,
                    a.key.prompt_version,
                ):
                    out.append(_comparison(a, b))
    return out


def load(root: Path, results_dir: Path | None = None) -> V2Data | None:
    """Everything the v2 sections need; None when no v2 results are committed."""
    v2_dir = (results_dir or root / "results") / "v2"
    groups = load_groups(v2_dir) if v2_dir.is_dir() else {}
    groups = {k: v for k, v in groups.items() if k.provider != "fake"}
    if not groups:
        return None
    configs, comparisons = analyse(groups)
    plan = load_plan(root / PLAN) if (root / PLAN).is_file() else {"runs": []}
    units = expand(plan, prompts.resolve_version(None))
    counts = {name: len(load_task_set(name, root)) for name in TASK_SETS}
    missing = []
    for u in units:
        path = v2_dir / f"{u.name}.jsonl"
        recs = read_records(path) if path.is_file() else []
        bad = [r for r in recs if r.get("harness_error")]
        if len(recs) < counts[u.task_set] or bad:
            missing.append(f"{u.name} ({len(recs)}/{counts[u.task_set]} tasks, {len(bad)} errors)")
    quant_models = list(
        dict.fromkeys(
            r["model"]
            for r in plan.get("runs", [])
            if str(r.get("round")) == "6.3" and r.get("provider") == "ollama"
        )
    )
    headers: dict[ConfigKey, dict[str, Any]] = {}
    for path in sorted(v2_dir.glob("*.jsonl")):
        header = read_header(path)
        if header is not None and header.get("provider") != "fake":
            headers.setdefault(config_key(header), header)
    records = {k: [r for seed in sorted(v) for r in v[seed]] for k, v in groups.items()}
    return V2Data(
        configs=configs,
        comparisons=comparisons + _extra_comparisons(configs, quant_models),
        records=records,
        headers=headers,
        plan=plan,
        missing=missing,
        planned_files=len(units),
        quant_models=quant_models,
    )


def _order(data: V2Data) -> list[ConfigStats]:
    """Configurations in plan order (dev before held-out), then anything not in the plan."""
    latest = prompts.resolve_version(None)
    rank: dict[tuple[str, str, int, str], int] = {}
    for i, r in enumerate(data.plan.get("runs", [])):
        key = (r["provider"], r["model"], int(r.get("prompt_version") or latest), r["mode"])
        rank.setdefault(key, i)
    sets = list(TASK_SETS)

    def sort_key(c: ConfigStats) -> tuple[int, int, str]:
        k = c.key
        pos = rank.get((k.provider, k.model, k.prompt_version, k.mode), len(rank))
        return (sets.index(k.task_set) if k.task_set in sets else len(sets), pos, k.label)

    return sorted(data.configs, key=sort_key)


def _name(k: ConfigKey) -> str:
    return f"`{k.model}` p{k.prompt_version} {k.mode}"


def _completeness(data: V2Data) -> list[str]:
    out = ["\n## Completeness\n"]
    if data.missing:
        out.append(
            f"{len(data.missing)} of {data.planned_files} planned results files are missing or "
            "incomplete; their rows below use only the seeds that exist:\n"
        )
        out += [f"- {m}" for m in data.missing]
    else:
        out.append(
            f"All {data.planned_files} results files planned in `{PLAN.as_posix()}` are complete, "
            "with no harness errors. No held-out task is excluded."
        )
    return out


def _headline(data: V2Data) -> list[str]:
    out = [
        "\n## Success with 95 % confidence intervals\n",
        "Temperature 0.7, one results file per seed. Success is the mean over seeds; the 95 % "
        "CI is a bootstrap over tasks (10 000 resamples, fixed RNG seed); `all / some / none` "
        "counts tasks solved in every seed, in some, in none (pass^k). `unverified`: answers "
        "returned with verifier findings left when the budget ran out (`solved_unverified`, "
        "judged by the checker like any answer).\n",
        "![Success with 95 % CI by model, mode and task set](v2_chart.png)\n",
        "| task set | model | prompt | mode | tasks x seeds | success (95 % CI) | seed min-max "
        "| all / some / none | unverified | median latency |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in _order(data):
        k, s, r = c.key, c.success, c.reliability
        recs = data.records[k]
        unverified = sum(1 for x in recs if x["status"] == "solved_unverified")
        latency = _median([float(x["latency_s"]) for x in recs])
        out.append(
            f"| {k.task_set} | `{k.model}` | v{k.prompt_version} | {k.mode} | "
            f"{s.n_tasks} x {s.n_seeds} | {_ci(c)} | {_pct(s.seed_min)} - {_pct(s.seed_max)} | "
            f"{r.all_seeds} / {r.some_seeds} / {r.no_seed} | {unverified} | "
            f"{_fmt(latency, '.1f', ' s')} |"
        )
    return out


def _comparisons(data: V2Data) -> list[str]:
    out = [
        "\n## Paired comparisons\n",
        "Same model and task set on both sides; the difference is a minus b in success rate, "
        "bootstrapped over tasks (paired by task). A difference whose 95 % CI includes 0 is "
        'reported as "no measurable difference" (R-STAT-6). McNemar: exact test on seed 0, '
        "with the tasks only a passed / only b passed.\n",
        "| task set | a | b | difference | McNemar seed 0 (a only / b only, p) |",
        "|---|---|---|---|---|",
    ]
    sets = list(TASK_SETS)
    for cmp in sorted(
        data.comparisons,
        key=lambda c: (sets.index(c.a.task_set) if c.a.task_set in sets else 9, c.a, c.b),
    ):
        p, mc = cmp.paired, cmp.mcnemar_seed0
        mc_text = "n/a" if mc is None else f"{mc.a_only} / {mc.b_only}, p = {mc.p_value:.3f}"
        out.append(
            f"| {cmp.a.task_set} | {_name(cmp.a)} | {_name(cmp.b)} | "
            f"{difference_wording(p.diff, p.ci_low, p.ci_high)} | {mc_text} |"
        )
    return out


def _verifier(data: V2Data, tasks: dict[str, Task]) -> list[str]:
    out = [
        "\n## Verifier quality\n",
        "Computed for every mode from the recorded answers and traces (the verifier is a pure "
        "function of recorded data), so baseline and repair rows show what verification *would* "
        "have flagged. `checked`: attempts that produced a result. `catches`: attempts the "
        "verifier failed that the checker also judges wrong. `false alarms`: attempts the "
        "verifier failed that the checker judges correct. `misses`: final answers the checker "
        "judges wrong that the verifier passed. `wrong answers`: final outcomes classed "
        "`wrong_answer:*` by the taxonomy. `flagged tasks -> passed / refused`: task outcomes "
        "with at least one flagged attempt, and how many of them ended passed or refused (in "
        "`verify` mode the findings go back to the model; in the other modes they do not).\n",
        "| task set | model | prompt | mode | checked | flagged | catches | false alarms | "
        "misses | wrong answers | flagged tasks -> passed / refused | flagged by check | "
        "false alarms by check |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in _order(data):
        k = c.key
        recs = data.records[k]
        q = verifier_quality(recs)
        if q is None:
            continue
        flagged = [r for r in recs if any(a["verifier_failed"] for a in r["attempt_checks"])]
        after = (
            f"{len(flagged)} -> {sum(1 for r in flagged if r['passed'])} / "
            f"{sum(1 for r in flagged if r['status'] == 'refused')}"
        )
        wrong = sum(
            1
            for r in recs
            if r["task_id"] in tasks
            and classify(r, tasks[r["task_id"]]).cls.startswith("wrong_answer")
        )
        by = ", ".join(f"{cid} {n}" for cid, n in q["failed_by_check"].items()) or "-"
        fa = ", ".join(f"{cid} {n}" for cid, n in q["false_alarms_by_check"].items()) or "-"
        out.append(
            f"| {k.task_set} | `{k.model}` | v{k.prompt_version} | {k.mode} | "
            f"{q['results_checked']} | {q['verifier_failed']} | {q['catches']} | "
            f"{q['false_alarms']} | {q['misses']} | {wrong} | {after} | {by} | {fa} |"
        )
    return out


def _refusals(data: V2Data, tasks: dict[str, Task]) -> list[str]:
    out = [
        "\n## Refusal and ambiguity (R-REF-3)\n",
        "Task outcomes (tasks x seeds). `not refused`: an adversarial task executed instead of "
        "refused. `missed error report`: an ambiguous task answered with a number instead of an "
        "error. `false refusal`: a legitimate task refused (any category); `after a failed "
        "attempt`: of those, the refusals that came after an earlier attempt failed (crash, "
        "format, policy or verifier finding), i.e. in reply to the repair prompt rather than as "
        "the first reply.\n",
        "| task set | model | prompt | mode | adversarial ok / outcomes | ambiguous ok / outcomes "
        "| not refused | missed error report | false refusal | after a failed attempt |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in _order(data):
        k = c.key
        counts: Counter[str] = Counter()
        cat_ok: Counter[str] = Counter()
        cat_n: Counter[str] = Counter()
        late = 0
        for r in data.records[k]:
            task = tasks.get(r["task_id"])
            if task is None:
                continue
            cls = classify(r, task).cls
            counts[cls] += 1
            cat_n[task.category] += 1
            cat_ok[task.category] += cls == "ok"
            late += cls == "false_refusal" and int(r["attempts"]) > 1
        adv, amb = "adversarial", "ambiguous_or_misleading"
        out.append(
            f"| {k.task_set} | `{k.model}` | v{k.prompt_version} | {k.mode} | "
            f"{cat_ok[adv]} / {cat_n[adv]} | {cat_ok[amb]} / {cat_n[amb]} | "
            + " | ".join(str(counts[x]) for x in REFUSAL_CLASSES)
            + f" | {late} |"
        )
    return out


@dataclass(frozen=True)
class QuantRow:
    model: str
    quantization: str
    dev: ConfigStats | None
    heldout: ConfigStats | None
    latency_s: float | None
    tokens_per_s: float | None
    ttft_s: float | None
    size_mib: int | None
    vram_mib: int | None
    gpu_fraction: float | None


def quant_rows(data: V2Data) -> list[QuantRow]:
    rows = []
    for model in [QUANT_BASE, *data.quant_models]:
        keys = [
            k
            for k in data.records
            if (k.model, k.mode, k.provider) == (model, QUANT_MODE, "ollama")
            and k.prompt_version == prompts.resolve_version(None)
        ]
        if not keys:
            continue
        recs = [r for k in keys for r in data.records[k]]
        sizes = [int(r["model_size_mib"]) for r in recs if r.get("model_size_mib") is not None]
        vram = [int(r["model_vram_mib"]) for r in recs if r.get("model_vram_mib") is not None]
        frac = [float(r["gpu_fraction"]) for r in recs if r.get("gpu_fraction") is not None]
        quant = str(data.headers.get(keys[0], {}).get("quantization") or "n/a")
        rows.append(
            QuantRow(
                model=model,
                quantization=quant,
                dev=data.stats(model, QUANT_MODE, "dev"),
                heldout=data.stats(model, QUANT_MODE, "heldout"),
                latency_s=_median([float(r["latency_s"]) for r in recs]),
                tokens_per_s=_median(
                    [t for r in recs for t in r.get("tokens_per_s") or [] if t is not None]
                ),
                ttft_s=_median([t for r in recs for t in r.get("ttft_s") or [] if t is not None]),
                size_mib=max(sizes) if sizes else None,
                vram_mib=max(vram) if vram else None,
                gpu_fraction=min(frac) if frac else None,
            )
        )
    return rows


def _quant(data: V2Data) -> list[str]:
    rows = quant_rows(data)
    out = ["\n## Quantisation and VRAM study (R-QV)\n"]
    if not rows:
        return [*out, "No quantisation runs committed yet."]
    out += [
        f"Mode `{QUANT_MODE}`, prompt v{prompts.resolve_version(None)}, on a 4 GB laptop GPU "
        "(RTX 3050 Mobile). Model size and VRAM come from Ollama's running-models API "
        "(`/api/ps`: `size`, `size_vram`), sampled during the run: the largest value seen. "
        "`on GPU` is `size_vram / size` (smallest seen); the rest runs on the CPU. Latency, "
        "tokens/s and TTFT are medians over every task (and every model call) of both task "
        "sets. The 3B Q4 row has 5 seeds, the others 3.\n",
        "![Success vs latency, point size = VRAM](quant_chart.png)\n",
        "| model | quantisation | dev success (95 % CI) | held-out success (95 % CI) | median "
        "latency | median tokens/s | median TTFT | model size | VRAM | on GPU |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for q in rows:
        out.append(
            f"| `{q.model}` | {q.quantization} | {_ci(q.dev) if q.dev else 'n/a'} | "
            f"{_ci(q.heldout) if q.heldout else 'n/a'} | {_fmt(q.latency_s, '.1f', ' s')} | "
            f"{_fmt(q.tokens_per_s, '.1f')} | {_fmt(q.ttft_s, '.2f', ' s')} | "
            f"{_fmt(q.size_mib, ',', ' MiB')} | {_fmt(q.vram_mib, ',', ' MiB')} | "
            f"{_fmt(None if q.gpu_fraction is None else 100 * q.gpu_fraction, '.0f', ' %')} |"
        )
    out.append(
        "\nPaired differences against the 3B Q4 row are in the paired-comparisons table above."
    )
    return out


def render_section(root: Path, results_dir: Path | None = None) -> str:
    data = load(root, results_dir)
    out = ["\n# v2 results"]
    if data is None:
        return "\n".join([*out, "No v2 results have been committed yet.\n"])
    tasks = _tasks(root)
    out += _completeness(data)
    out += _headline(data)
    out += _comparisons(data)
    out += _verifier(data, tasks)
    out += _refusals(data, tasks)
    out += _quant(data)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------- README block


def headline_models(data: V2Data) -> list[str]:
    """Models of the main matrix (blocks 6.1 and 6.2), in plan order."""
    return list(
        dict.fromkeys(
            r["model"]
            for r in data.plan.get("runs", [])
            if str(r.get("round")) in ("6.1", "6.2") and not r.get("prompt_version")
        )
    )


def readme_rows(data: V2Data) -> list[str]:
    latest = prompts.resolve_version(None)
    lines = [
        "| model | task set | baseline | repair | verify |",
        "|---|---|---|---|---|",
    ]
    for model in headline_models(data):
        for task_set in TASK_SETS:
            cells = []
            for mode in MODES:
                c = data.stats(model, mode, task_set, latest)
                planned = any(
                    (r["model"], r["mode"]) == (model, mode) for r in data.plan.get("runs", [])
                )
                cells.append(_ci(c) if c else ("not run" if planned else "not planned"))
            lines.append(f"| `{model}` | {task_set} | " + " | ".join(cells) + " |")
    return lines


# ---------------------------------------------------------------------------- charts


def _style(ax: Any) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def render_chart(data: V2Data, out: Path) -> None:
    """Success with 95 % CI per model, baseline -> repair -> verify; dev and held-out panels."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    models = headline_models(data)
    latest = prompts.resolve_version(None)
    sets = list(TASK_SETS)
    fig, axes = plt.subplots(
        1, len(sets), figsize=(11, 0.9 * len(models) + 1.9), dpi=150, facecolor=SURFACE, sharey=True
    )
    for ax, task_set in zip(axes, sets, strict=True):
        _style(ax)
        for j, mode in enumerate(MODES):
            first = True
            for i, model in enumerate(models):
                c = data.stats(model, mode, task_set, latest)
                if c is None:
                    continue
                y = i + (j - 1) * 0.24
                s = c.success
                ax.errorbar(
                    100 * s.mean,
                    y,
                    xerr=[[100 * (s.mean - s.ci_low)], [100 * (s.ci_high - s.mean)]],
                    fmt="o",
                    markersize=6,
                    color=MODE_COLOURS[mode],
                    ecolor=MODE_COLOURS[mode],
                    elinewidth=2,
                    capsize=0,
                    markeredgecolor=SURFACE,
                    markeredgewidth=1.5,
                    label=mode if first else None,
                )
                first = False
                ax.text(
                    100 * s.ci_high + 1.5,
                    y,
                    f"{100 * s.mean:.0f}%",
                    va="center",
                    fontsize=7,
                    color=INK_2,
                )
        ax.set_yticks(range(len(models)), models)
        ax.set_xlim(0, 112)
        ax.set_ylim(len(models) - 0.5, -0.5)
        name = "held-out (frozen before the verifier)" if task_set == "heldout" else "dev"
        n = next((c.success.n_tasks for c in data.configs if c.key.task_set == task_set), 0)
        ax.set_title(f"{name}, {n} tasks", color=INK, fontsize=10, loc="left")
        ax.set_xlabel("success, mean over seeds (%), with 95 % CI", color=INK_2, fontsize=8)
    axes[0].legend(
        frameon=False,
        fontsize=8,
        labelcolor=INK,
        ncol=3,
        loc="lower left",
        bbox_to_anchor=(0, 1.08),
    )
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def render_quant_chart(data: V2Data, out: Path) -> None:
    """R-QV-3: success vs median latency, point size = VRAM footprint; one colour per task set."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = quant_rows(data)
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150, facecolor=SURFACE)
    _style(ax)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    vmax = max((q.vram_mib or 0) for q in rows) or 1
    first = dict.fromkeys(SET_COLOURS, True)
    for q in rows:
        if q.latency_s is None:
            continue
        ys = []
        for task_set, colour in SET_COLOURS.items():
            c = q.dev if task_set == "dev" else q.heldout
            if c is None:
                continue
            ys.append(100 * c.success.mean)
            ax.scatter(
                q.latency_s,
                ys[-1],
                s=60 + 340 * (q.vram_mib or 0) / vmax,
                color=colour,
                edgecolors=SURFACE,
                linewidths=2,
                label=("held-out" if task_set == "heldout" else "dev") if first[task_set] else None,
                zorder=3,
            )
            first[task_set] = False
        if not ys:
            continue
        # Connect a model's dev and held-out points; one label per model, at their midpoint.
        ax.plot([q.latency_s] * len(ys), ys, color=GRID, linewidth=2, zorder=2)
        on_gpu = "n/a" if q.gpu_fraction is None else f"{100 * q.gpu_fraction:.0f} %"
        ax.annotate(
            f"{_short(q.model)} {q.quantization}\n"
            f"model {_fmt(q.size_mib, ',')} MiB, VRAM {_fmt(q.vram_mib, ',')} MiB "
            f"({on_gpu} on GPU)",
            (q.latency_s, sum(ys) / len(ys)),
            textcoords="offset points",
            xytext=(14, 0),
            va="center",
            fontsize=7,
            color=INK_2,
        )
    lat = [q.latency_s for q in rows if q.latency_s is not None]
    ax.set_xlim(0, 1.9 * max(lat) if lat else 1)
    ax.set_ylim(0, 100)
    ax.set_xlabel("median end-to-end latency per task (s)", color=INK_2, fontsize=8)
    ax.set_ylabel("success, verify mode (%)", color=INK_2, fontsize=8)
    ax.set_title(
        "Quantisation study on a 4 GB GPU: point size = VRAM used by the model",
        color=INK,
        fontsize=10,
        loc="left",
    )
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right", markerscale=0.6)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def write_charts(root: Path, docs: Path, results_dir: Path | None = None) -> None:
    data = load(root, results_dir)
    for name in (CHART, QUANT_CHART):
        if data is None and (docs / name).exists():
            (docs / name).unlink()
    if data is None:
        return
    render_chart(data, docs / CHART)
    if quant_rows(data):
        render_quant_chart(data, docs / QUANT_CHART)

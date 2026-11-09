"""v2 benchmark plan: expansion into results files, progress and ETA (PLAN-v2 2.4).

A plan (``data/bench_plan_v2.json``) lists runs as ``{round, provider, model, mode, task_set,
seeds, delay_s?, vram?, prompt_version?, note?}``. Each run expands into one *unit* per
(task set, seed): exactly one results file, named like ``scripts/evaluate.py`` names it. The ETA
is the number of remaining tasks times the median per-task time (latency plus the configured
delay) of finished records, taken from the most similar finished runs (same provider, model and
mode; else same provider and model; else none, in which case the ETA is unknown).
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simagent.evaluation.harness import MODES, done_task_ids, run_name_for
from simagent.evaluation.summary import read_records
from simagent.evaluation.tasks import TASK_SETS

V2_MODES = (*MODES, "verify")  # "verify" arrives with the verifier (PLAN-v2 Phase 4)
PROVIDERS = ("ollama", "groq", "openai", "fake")
REQUIRED = {"round", "provider", "model", "mode", "task_set", "seeds"}
OPTIONAL = {"delay_s", "vram", "prompt_version", "note"}


@dataclass(frozen=True)
class Unit:
    """One results file of the plan: a (run, task set, seed)."""

    round: str
    provider: str
    model: str
    mode: str
    task_set: str
    seed: int
    prompt_version: int
    delay_s: float = 0.0
    vram: bool = False

    @property
    def name(self) -> str:
        return run_name_for(
            self.provider, self.model, self.mode, self.prompt_version, self.task_set, self.seed
        )

    def evaluate_args(self, results_dir: Path, runs_dir: Path) -> list[str]:
        args = [
            "--provider",
            self.provider,
            "--model",
            self.model,
            "--mode",
            self.mode,
            "--task-set",
            self.task_set,
            "--seeds",
            str(self.seed),
            "--prompt-version",
            str(self.prompt_version),
            "--resume",
            "--results-dir",
            str(results_dir),
            "--runs-dir",
            str(runs_dir),
        ]
        if self.delay_s:
            args += ["--delay", f"{self.delay_s:g}"]
        if self.vram:
            args.append("--vram")
        return args


def _validate(entry: Mapping[str, Any], i: int) -> None:
    missing = REQUIRED - set(entry)
    unknown = set(entry) - REQUIRED - OPTIONAL
    if missing or unknown:
        raise ValueError(f"plan run {i}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    if entry["provider"] not in PROVIDERS:
        raise ValueError(f"plan run {i}: unknown provider {entry['provider']!r}")
    if entry["mode"] not in V2_MODES:
        raise ValueError(f"plan run {i}: mode must be one of {V2_MODES}")
    if entry["task_set"] not in (*TASK_SETS, "all"):
        raise ValueError(f"plan run {i}: unknown task set {entry['task_set']!r}")
    seeds = entry["seeds"]
    if (
        not isinstance(seeds, list)
        or not seeds
        or not all(isinstance(s, int) and s >= 0 for s in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError(f"plan run {i}: seeds must be distinct non-negative integers")


def expand(plan: Mapping[str, Any], latest_prompt: int) -> list[Unit]:
    """Validate the plan and expand it into units, in plan order (task set, then seed)."""
    units: list[Unit] = []
    for i, entry in enumerate(plan.get("runs", [])):
        _validate(entry, i)
        sets = list(TASK_SETS) if entry["task_set"] == "all" else [entry["task_set"]]
        for task_set in sets:
            for seed in entry["seeds"]:
                units.append(
                    Unit(
                        round=str(entry["round"]),
                        provider=entry["provider"],
                        model=entry["model"],
                        mode=entry["mode"],
                        task_set=task_set,
                        seed=seed,
                        prompt_version=int(entry.get("prompt_version") or latest_prompt),
                        delay_s=float(entry.get("delay_s", 0.0)),
                        vram=bool(entry.get("vram", False)),
                    )
                )
    names = [u.name for u in units]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"plan lists the same results file twice: {dupes}")
    return units


def load_plan(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@dataclass(frozen=True)
class Progress:
    unit: Unit
    done: int
    total: int

    @property
    def state(self) -> str:
        if self.done >= self.total:
            return "complete"
        return "not started" if self.done == 0 else "partial"


def progress(
    units: Iterable[Unit], staging: Path, task_counts: Mapping[str, int]
) -> list[Progress]:
    return [
        Progress(u, len(done_task_ids(staging / f"{u.name}.jsonl")), task_counts[u.task_set])
        for u in units
    ]


def task_seconds(staging: Path, units: Iterable[Unit]) -> dict[Unit, list[float]]:
    """Per-task wall time (latency + delay) of the finished records of each unit."""
    out: dict[Unit, list[float]] = {}
    for u in units:
        path = staging / f"{u.name}.jsonl"
        if path.is_file():
            out[u] = [float(r["latency_s"]) + u.delay_s for r in read_records(path)]
    return out


def median_task_s(unit: Unit, timings: Mapping[Unit, list[float]]) -> float | None:
    """Median per-task time from the most similar finished units; None if none exist."""

    def pick(match: Any) -> list[float]:
        return [t for u, ts in timings.items() if match(u) for t in ts]

    for match in (
        lambda u: (u.provider, u.model, u.mode) == (unit.provider, unit.model, unit.mode),
        lambda u: (u.provider, u.model) == (unit.provider, unit.model),
    ):
        values = pick(match)
        if values:
            return float(statistics.median(values))
    return None


def eta_s(rows: Iterable[Progress], timings: Mapping[Unit, list[float]]) -> tuple[float, int]:
    """(Estimated seconds for the remaining tasks with a known median, remaining tasks without)."""
    known, unknown = 0.0, 0
    for row in rows:
        remaining = row.total - row.done
        if remaining <= 0:
            continue
        median = median_task_s(row.unit, timings)
        if median is None:
            unknown += remaining
        else:
            known += remaining * median
    return known, unknown


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"

"""Metrics over one evaluation run's JSONL records (R-EV-6).

Every number here is computed from the records; values that were not measured stay ``None``.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from simagent.evaluation.verifier_quality import verifier_quality


def read_records(path: Path) -> list[dict[str, Any]]:
    """Task records of a results JSONL file (header skipped; last record wins per task id)."""
    by_id: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("kind") == "header":  # v2 results header (R-STAT-2), not a task
                continue
            by_id[rec["task_id"]] = rec
    return list(by_id.values())


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _p90(values: list[float]) -> float | None:
    return float(np.percentile(values, 90)) if values else None


def _total(records: list[dict[str, Any]], key: str) -> int | None:
    values = [r.get(key) for r in records]
    if not values or any(v is None for v in values):
        return None
    return int(sum(v for v in values if v is not None))


def _max_of(records: list[dict[str, Any]], key: str) -> Any:
    values = [r[key] for r in records if r.get(key) is not None]
    return max(values) if values else None


def _min_of(records: list[dict[str, Any]], key: str) -> Any:
    values = [r[key] for r in records if r.get(key) is not None]
    return min(values) if values else None


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run metrics: success rates, repairs, failures, latency, throughput, tokens, cost."""
    n = len(records)
    passed = [r for r in records if r["passed"]]
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)
    ttft = [t for r in records for t in r.get("ttft_s") or [] if t is not None]
    tps = [t for r in records for t in r.get("tokens_per_s") or [] if t is not None]
    costs = [r.get("cost_usd") for r in records]
    vram = [r["peak_vram_mib"] for r in records if r.get("peak_vram_mib") is not None]
    first = records[0] if records else {}
    return {
        "provider": first.get("provider"),
        "model": first.get("model"),
        "mode": first.get("mode"),
        "prompt_version": first.get("prompt_version"),
        "max_attempts": first.get("max_attempts"),
        "tasks": n,
        "passed": len(passed),
        "success_rate": len(passed) / n if n else None,
        "success_rate_by_category": {
            cat: sum(r["passed"] for r in rs) / len(rs) for cat, rs in sorted(by_cat.items())
        },
        "tasks_by_category": {cat: len(rs) for cat, rs in sorted(by_cat.items())},
        "mean_attempts_solved": (
            float(np.mean([r["attempts"] for r in passed])) if passed else None
        ),
        "repaired_successes": sum(1 for r in passed if r["attempts"] > 1),
        "status_solved_but_wrong": sum(
            1 for r in records if r["status"] == "solved" and not r["passed"]
        ),
        "status_solved_unverified": sum(1 for r in records if r["status"] == "solved_unverified"),
        "verifier": verifier_quality(records),
        "policy_violations": sum(r.get("policy_violations", 0) for r in records),
        "timeouts": sum(r.get("timeouts", 0) for r in records),
        "latency_median_s": _median([r["latency_s"] for r in records]),
        "latency_p90_s": _p90([r["latency_s"] for r in records]),
        "ttft_median_s": _median(ttft),
        "tokens_per_s_median": _median(tps),
        "input_tokens_total": _total(records, "input_tokens"),
        "output_tokens_total": _total(records, "output_tokens"),
        "cost_usd_total": (
            float(sum(c for c in costs if c is not None))
            if costs and all(c is not None for c in costs)
            else None
        ),
        "peak_vram_mib": max(vram) if vram else None,  # nvidia-smi total (includes the desktop)
        "model_size_mib": _max_of(records, "model_size_mib"),  # Ollama /api/ps (R-QV-2)
        "model_vram_mib": _max_of(records, "model_vram_mib"),
        "gpu_fraction": _min_of(records, "gpu_fraction"),
    }

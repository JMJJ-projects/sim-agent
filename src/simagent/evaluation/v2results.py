"""Group v2 results files into configurations and compute their statistics (R-STAT-3..5).

A *configuration* is everything in a results header except the seed: provider, model, prompt
version, mode, task set, temperature and attempt budget. Files whose headers agree on all of
these are the seeds of one configuration and become one outcome matrix (tasks x seeds).
v1 files (no header) are ignored: v1 and v2 results are never mixed (R-STAT-2).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simagent.evaluation.harness import read_header
from simagent.evaluation.stats import (
    McNemar,
    OutcomeMatrix,
    PairedDifference,
    Reliability,
    SuccessStats,
    mcnemar_on_seed,
    outcome_matrix,
    paired_difference,
    reliability,
    success_stats,
)
from simagent.evaluation.summary import read_records

# Paired comparisons the report makes: (mode a, mode b) means "a minus b" (R-STAT-4).
COMPARISONS = (("repair", "baseline"), ("verify", "repair"))


@dataclass(frozen=True, order=True)
class ConfigKey:
    provider: str
    model: str
    prompt_version: int
    task_set: str
    mode: str
    temperature: float | None
    max_attempts: int

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model} p{self.prompt_version} {self.mode} [{self.task_set}]"

    @property
    def setup(self) -> tuple[str, str, int, str, float | None]:
        """Everything but the mode and its attempt budget: what a paired comparison holds fixed."""
        return (self.provider, self.model, self.prompt_version, self.task_set, self.temperature)


def config_key(header: dict[str, Any]) -> ConfigKey:
    return ConfigKey(
        provider=str(header["provider"]),
        model=str(header["model"]),
        prompt_version=int(header["prompt_version"]),
        task_set=str(header["task_set"]),
        mode=str(header["mode"]),
        temperature=header.get("temperature"),
        max_attempts=int(header["max_attempts"]),
    )


def load_groups(results_dir: Path) -> dict[ConfigKey, dict[int, list[dict[str, Any]]]]:
    """Records per configuration and seed, from every v2 results file in ``results_dir``."""
    groups: dict[ConfigKey, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
    for path in sorted(results_dir.glob("*.jsonl")):
        header = read_header(path)
        if header is None:
            continue
        key, seed = config_key(header), int(header["seed"])
        if seed in groups[key]:
            raise ValueError(f"{path.name}: seed {seed} of {key.label} appears twice")
        groups[key][seed] = read_records(path)
    return dict(groups)


@dataclass(frozen=True)
class ConfigStats:
    key: ConfigKey
    matrix: OutcomeMatrix
    success: SuccessStats
    reliability: Reliability


@dataclass(frozen=True)
class Comparison:
    a: ConfigKey
    b: ConfigKey
    paired: PairedDifference
    mcnemar_seed0: McNemar | None  # None when seed 0 is missing from either side


def analyse(
    groups: dict[ConfigKey, dict[int, list[dict[str, Any]]]],
) -> tuple[list[ConfigStats], list[Comparison]]:
    """Stats per configuration and the paired comparisons between modes of the same setup."""
    configs = [
        ConfigStats(key, m, success_stats(m), reliability(m))
        for key, m in sorted((k, outcome_matrix(v)) for k, v in groups.items())
    ]
    by_key = {c.key: c for c in configs}
    comparisons: list[Comparison] = []
    for c in configs:
        for mode_a, mode_b in COMPARISONS:
            if c.key.mode != mode_a:
                continue
            partners = [k for k in by_key if k.mode == mode_b and k.setup == c.key.setup]
            for other in partners:
                b = by_key[other]
                both_seed0 = 0 in c.matrix.seeds and 0 in b.matrix.seeds
                comparisons.append(
                    Comparison(
                        c.key,
                        other,
                        paired_difference(c.matrix, b.matrix),
                        mcnemar_on_seed(c.matrix, b.matrix, 0) if both_seed0 else None,
                    )
                )
    return configs, comparisons

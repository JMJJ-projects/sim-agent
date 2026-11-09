"""Statistics for repeated evaluation runs (R-STAT-3..7). Pure functions, NumPy + ``math`` only.

Input is an *outcome matrix*: tasks x seeds, ``True`` where the task passed with that seed.

* **Success** (R-STAT-3): mean success rate over seeds, min-max over seeds, and a 95 % bootstrap
  CI over tasks: resample tasks with replacement (10 000 times, fixed RNG seed) and average each
  resampled task's success rate over seeds. Tasks are the unit of resampling because the task
  set is the main source of variation we want the interval to cover.
* **Paired difference** (R-STAT-4): per-task difference in success rate between two
  configurations on the same tasks, with the same task bootstrap; plus an **exact McNemar test**
  on one seed (binomial test on the discordant tasks, two-sided = twice the one-sided tail,
  capped at 1, as defined by Fagerland, Lydersen & Laake 2013, BMC Med Res Methodol 13:91).
* **Reliability** (R-STAT-5): tasks solved in all seeds, in some, in none ("pass^k" style).
* **Wording** (R-STAT-6): a difference whose 95 % CI includes 0 is "no measurable difference".
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261109  # fixed so every report regenerates identical intervals
CI_LEVEL = 0.95


@dataclass(frozen=True)
class OutcomeMatrix:
    """Pass/fail per task (rows, sorted ids) and seed (columns, sorted seeds)."""

    task_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    passed: NDArray[np.bool_]

    def __post_init__(self) -> None:
        if self.passed.shape != (len(self.task_ids), len(self.seeds)):
            raise ValueError(
                f"matrix shape {self.passed.shape} != ({len(self.task_ids)}, {len(self.seeds)})"
            )

    @property
    def per_task_rate(self) -> NDArray[np.float64]:
        """Each task's success rate over seeds."""
        return np.asarray(self.passed.mean(axis=1), dtype=np.float64)

    @property
    def per_seed_rate(self) -> NDArray[np.float64]:
        """Each seed's success rate over tasks."""
        return np.asarray(self.passed.mean(axis=0), dtype=np.float64)

    def column(self, seed: int) -> NDArray[np.bool_]:
        if seed not in self.seeds:
            raise ValueError(f"seed {seed} not in {self.seeds}")
        return np.asarray(self.passed[:, self.seeds.index(seed)], dtype=np.bool_)


def outcome_matrix(records_by_seed: Mapping[int, Iterable[Mapping[str, Any]]]) -> OutcomeMatrix:
    """Build the matrix from task records (``task_id``, ``passed``) per seed.

    Every seed must cover exactly the same tasks: an incomplete run would bias the comparison.
    """
    if not records_by_seed:
        raise ValueError("no seeds")
    by_seed: dict[int, dict[str, bool]] = {
        seed: {str(r["task_id"]): bool(r["passed"]) for r in recs}
        for seed, recs in records_by_seed.items()
    }
    seeds = tuple(sorted(by_seed))
    task_ids = tuple(sorted(by_seed[seeds[0]]))
    for seed in seeds:
        if set(by_seed[seed]) != set(task_ids):
            missing = sorted(set(task_ids) ^ set(by_seed[seed]))
            raise ValueError(f"seed {seed} covers different tasks than seed {seeds[0]}: {missing}")
    if not task_ids:
        raise ValueError("no tasks")
    passed = np.array([[by_seed[s][t] for s in seeds] for t in task_ids], dtype=np.bool_)
    return OutcomeMatrix(task_ids, seeds, passed)


def bootstrap_mean_ci(
    values: Sequence[float] | NDArray[np.float64],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = CI_LEVEL,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean of ``values`` (one value per task)."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("need a non-empty 1-D array")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_resamples, arr.size))
    means = arr[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = np.percentile(means, [100 * alpha, 100 * (1 - alpha)])
    return float(lo), float(hi)


@dataclass(frozen=True)
class SuccessStats:
    n_tasks: int
    n_seeds: int
    mean: float
    seed_min: float
    seed_max: float
    ci_low: float
    ci_high: float


def success_stats(m: OutcomeMatrix, **bootstrap: Any) -> SuccessStats:
    """R-STAT-3: mean over seeds, min-max over seeds, 95 % bootstrap CI over tasks."""
    per_seed = m.per_seed_rate
    lo, hi = bootstrap_mean_ci(m.per_task_rate, **bootstrap)
    return SuccessStats(
        n_tasks=len(m.task_ids),
        n_seeds=len(m.seeds),
        mean=float(m.per_task_rate.mean()),
        seed_min=float(np.min(per_seed)),
        seed_max=float(np.max(per_seed)),
        ci_low=lo,
        ci_high=hi,
    )


@dataclass(frozen=True)
class PairedDifference:
    n_tasks: int
    diff: float
    ci_low: float
    ci_high: float


def _aligned(a: OutcomeMatrix, b: OutcomeMatrix) -> None:
    if a.task_ids != b.task_ids:
        only = sorted(set(a.task_ids) ^ set(b.task_ids))
        raise ValueError(f"paired comparison needs the same tasks; differing: {only}")


def paired_difference(a: OutcomeMatrix, b: OutcomeMatrix, **bootstrap: Any) -> PairedDifference:
    """R-STAT-4: success rate of ``a`` minus ``b``, bootstrapped over tasks (paired by task)."""
    _aligned(a, b)
    d = a.per_task_rate - b.per_task_rate
    lo, hi = bootstrap_mean_ci(d, **bootstrap)
    return PairedDifference(n_tasks=len(d), diff=float(d.mean()), ci_low=lo, ci_high=hi)


@dataclass(frozen=True)
class McNemar:
    a_only: int  # tasks passed by a and failed by b
    b_only: int  # tasks failed by a and passed by b
    p_value: float


def mcnemar_exact(a_passed: Sequence[bool], b_passed: Sequence[bool]) -> McNemar:
    """Exact (conditional) McNemar test on paired pass/fail outcomes.

    Under H0 the discordant pairs split 50/50: the one-sided p-value is the binomial tail
    P(X <= min(a_only, b_only)) with n = a_only + b_only, p = 1/2; two-sided = twice that,
    capped at 1 (1.0 when there are no discordant pairs).
    """
    if len(a_passed) != len(b_passed):
        raise ValueError("outcome lists differ in length")
    a_only = sum(1 for x, y in zip(a_passed, b_passed, strict=True) if x and not y)
    b_only = sum(1 for x, y in zip(a_passed, b_passed, strict=True) if y and not x)
    n = a_only + b_only
    if n == 0:
        return McNemar(0, 0, 1.0)
    tail = sum(math.comb(n, k) for k in range(min(a_only, b_only) + 1))
    p = min(1.0, 2.0 * tail / 2**n)
    return McNemar(a_only, b_only, p)


def mcnemar_on_seed(a: OutcomeMatrix, b: OutcomeMatrix, seed: int = 0) -> McNemar:
    """R-STAT-4: the exact McNemar test on one seed (default seed 0)."""
    _aligned(a, b)
    return mcnemar_exact(a.column(seed).tolist(), b.column(seed).tolist())


@dataclass(frozen=True)
class Reliability:
    k: int
    all_seeds: int
    some_seeds: int
    no_seed: int


def reliability(m: OutcomeMatrix) -> Reliability:
    """R-STAT-5: tasks solved in every seed, in some seeds, in none."""
    solved = m.passed.sum(axis=1)
    k = len(m.seeds)
    return Reliability(
        k=k,
        all_seeds=int((solved == k).sum()),
        some_seeds=int(((solved > 0) & (solved < k)).sum()),
        no_seed=int((solved == 0).sum()),
    )


def difference_wording(diff: float, ci_low: float, ci_high: float) -> str:
    """R-STAT-6: how a difference in success rate (fractions) may be described.

    A difference whose 95 % CI includes 0 is never called an improvement or a drop.
    """
    if ci_low > ci_high:
        raise ValueError("ci_low must not exceed ci_high")
    ci = f"95 % CI {100 * ci_low:+.1f} to {100 * ci_high:+.1f} pp"
    if ci_low <= 0.0 <= ci_high:
        return f"no measurable difference ({100 * diff:+.1f} pp, {ci})"
    if ci_low > 0.0:
        return f"improvement of {100 * diff:.1f} pp ({ci})"
    return f"drop of {100 * -diff:.1f} pp ({ci})"

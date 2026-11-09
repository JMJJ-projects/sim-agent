"""Statistics for repeated runs (R-STAT-3..7), checked against hand-computed and published cases."""

import numpy as np
import pytest

from simagent.evaluation import stats
from simagent.evaluation.stats import (
    OutcomeMatrix,
    bootstrap_mean_ci,
    difference_wording,
    mcnemar_exact,
    mcnemar_on_seed,
    outcome_matrix,
    paired_difference,
    reliability,
    success_stats,
)


def _m(rows: list[list[bool]], seeds: tuple[int, ...] | None = None) -> OutcomeMatrix:
    ids = tuple(f"t{i}" for i in range(len(rows)))
    return OutcomeMatrix(ids, seeds or tuple(range(len(rows[0]))), np.array(rows, dtype=bool))


def _recs(passed: dict[str, bool]) -> list[dict[str, object]]:
    return [{"task_id": t, "passed": p} for t, p in passed.items()]


def test_outcome_matrix_from_records() -> None:
    """Covers R-STAT-7: tasks x seeds, rows and columns sorted."""
    m = outcome_matrix(
        {
            1: _recs({"b": True, "a": False}),
            0: _recs({"a": True, "b": True}),
        }
    )
    assert m.task_ids == ("a", "b")
    assert m.seeds == (0, 1)
    assert m.passed.tolist() == [[True, False], [True, True]]
    assert m.per_task_rate.tolist() == [0.5, 1.0]
    assert m.per_seed_rate.tolist() == [1.0, 0.5]


def test_outcome_matrix_rejects_incomplete_runs() -> None:
    with pytest.raises(ValueError, match="different tasks"):
        outcome_matrix({0: _recs({"a": True, "b": True}), 1: _recs({"a": True})})
    with pytest.raises(ValueError, match="no seeds"):
        outcome_matrix({})
    with pytest.raises(ValueError, match="no tasks"):
        outcome_matrix({0: []})
    with pytest.raises(ValueError, match="shape"):
        OutcomeMatrix(("a",), (0, 1), np.array([[True]]))
    with pytest.raises(ValueError, match="seed 5"):
        _m([[True]]).column(5)


def test_bootstrap_hand_computed_cases() -> None:
    """Covers R-STAT-3/7 with a fixed RNG seed.

    Constant values: every resample has the same mean, so the CI collapses to it. Values [0, 1]:
    resample means are 0, 0.5, 1 with probabilities 1/4, 1/2, 1/4, so with 10 000 resamples the
    2.5 % and 97.5 % percentiles are 0 and 1.
    """
    assert bootstrap_mean_ci([0.4, 0.4, 0.4]) == pytest.approx((0.4, 0.4))
    assert bootstrap_mean_ci([0.0, 1.0]) == (0.0, 1.0)
    assert bootstrap_mean_ci([1.0]) == (1.0, 1.0)


def test_bootstrap_is_reproducible_and_brackets_the_mean() -> None:
    values = np.linspace(0.0, 1.0, 40)
    first = bootstrap_mean_ci(values)
    assert bootstrap_mean_ci(values) == first
    assert bootstrap_mean_ci(values, seed=1) != first
    lo, hi = first
    assert lo < values.mean() < hi
    # Normal approximation for a mean of 40 values: half-width ~ 1.96 * sd / sqrt(40).
    half = 1.96 * values.std() / np.sqrt(values.size)
    assert (hi - lo) / 2 == pytest.approx(half, rel=0.1)
    assert stats.BOOTSTRAP_RESAMPLES == 10_000


def test_bootstrap_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        bootstrap_mean_ci([])


def test_success_stats() -> None:
    """Covers R-STAT-3: per-seed rates 3/4 and 1/4, per-task rates [1, 0.5, 0, 0.5]."""
    m = _m([[True, True], [True, False], [False, False], [True, False]])
    s = success_stats(m)
    assert (s.n_tasks, s.n_seeds) == (4, 2)
    assert s.mean == 0.5
    assert (s.seed_min, s.seed_max) == (0.25, 0.75)
    assert s.ci_low <= 0.5 <= s.ci_high
    assert s.ci_low >= 0.0
    assert s.ci_high <= 1.0


def test_paired_difference() -> None:
    """Covers R-STAT-4: identical configs differ by exactly 0; all-vs-nothing by exactly 1."""
    a = _m([[True, True], [True, True], [True, True]])
    b = _m([[False, False], [False, False], [False, False]])
    same = paired_difference(a, a)
    assert (same.diff, same.ci_low, same.ci_high) == (0.0, 0.0, 0.0)
    full = paired_difference(a, b)
    assert (full.n_tasks, full.diff, full.ci_low, full.ci_high) == (3, 1.0, 1.0, 1.0)
    mixed = paired_difference(_m([[True, False], [True, True]]), _m([[False, False], [True, True]]))
    assert mixed.diff == 0.25  # per-task differences 0.5 and 0
    assert (mixed.ci_low, mixed.ci_high) == (0.0, 0.5)


def test_paired_difference_needs_same_tasks() -> None:
    a = OutcomeMatrix(("x",), (0,), np.array([[True]]))
    b = OutcomeMatrix(("y",), (0,), np.array([[True]]))
    with pytest.raises(ValueError, match="same tasks"):
        paired_difference(a, b)


def _pairs(a_only: int, b_only: int, both: int, neither: int) -> tuple[list[bool], list[bool]]:
    a = [True] * a_only + [False] * b_only + [True] * both + [False] * neither
    b = [False] * a_only + [True] * b_only + [True] * both + [False] * neither
    return a, b


def test_mcnemar_published_examples() -> None:
    """Covers R-STAT-4/7 against Fagerland, Lydersen & Laake (2013), BMC Med Res Methodol 13:91,
    Table 6, "McNemar exact" row: Bentur et al. (discordant 1 and 7) p = 0.0703; Cavo et al.
    (table 59, 6, 16, 80) p = 0.0525."""
    bentur = mcnemar_exact(*_pairs(1, 7, both=1, neither=12))
    assert (bentur.a_only, bentur.b_only) == (1, 7)
    assert round(bentur.p_value, 4) == 0.0703
    cavo = mcnemar_exact(*_pairs(6, 16, both=59, neither=80))
    assert round(cavo.p_value, 4) == 0.0525
    # The same values by hand: 2 * (C(8,0) + C(8,1)) / 2^8 and 2 * sum C(22, 0..6) / 2^22.
    assert bentur.p_value == 2 * 9 / 256
    assert cavo.p_value == 2 * 110056 / 2**22


def test_mcnemar_edge_cases() -> None:
    assert mcnemar_exact([True, False], [True, False]).p_value == 1.0  # no discordant pairs
    assert mcnemar_exact(*_pairs(3, 3, 0, 0)).p_value == 1.0  # balanced: capped at 1
    one_way = mcnemar_exact(*_pairs(5, 0, 0, 0))
    assert one_way.p_value == 2 / 32
    assert mcnemar_exact(*_pairs(0, 5, 0, 0)).p_value == one_way.p_value  # symmetric
    with pytest.raises(ValueError, match="length"):
        mcnemar_exact([True], [])


def test_mcnemar_on_seed_uses_that_seed() -> None:
    a = _m([[True, False], [True, False]], seeds=(0, 1))
    b = _m([[False, True], [False, True]], seeds=(0, 1))
    s0 = mcnemar_on_seed(a, b)
    assert (s0.a_only, s0.b_only) == (2, 0)
    s1 = mcnemar_on_seed(a, b, seed=1)
    assert (s1.a_only, s1.b_only) == (0, 2)


def test_reliability_counts() -> None:
    """Covers R-STAT-5."""
    m = _m([[True, True, True], [True, False, False], [False, False, False], [True, True, False]])
    r = reliability(m)
    assert (r.k, r.all_seeds, r.some_seeds, r.no_seed) == (3, 1, 2, 1)


def test_difference_wording() -> None:
    """Covers R-STAT-6: a CI that includes 0 is never an improvement."""
    assert difference_wording(0.05, -0.01, 0.11).startswith("no measurable difference")
    assert difference_wording(0.0, 0.0, 0.0).startswith("no measurable difference")
    assert difference_wording(0.08, 0.0, 0.2).startswith("no measurable difference")
    assert difference_wording(0.083, 0.02, 0.15) == (
        "improvement of 8.3 pp (95 % CI +2.0 to +15.0 pp)"
    )
    assert difference_wording(-0.1, -0.2, -0.03) == "drop of 10.0 pp (95 % CI -20.0 to -3.0 pp)"
    assert "improvement" not in difference_wording(0.3, -0.001, 0.6)
    with pytest.raises(ValueError, match="ci_low"):
        difference_wording(0.0, 0.1, -0.1)

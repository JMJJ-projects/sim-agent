"""Print v2 statistics for a directory of results files (R-STAT-3..6).

    python scripts/stats_v2.py [--results-dir results/v2] [--min-seeds 2]

Per configuration: success rate (mean over seeds) with a 95 % bootstrap CI over tasks, min-max
over seeds, and how many tasks were solved in all / some / no seeds. Then the paired comparisons
(repair vs baseline, verify vs repair) with the difference's CI, its wording, and the exact
McNemar test on seed 0. Exit code 2 when there is nothing to analyse or too few seeds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simagent.evaluation.stats import difference_wording
from simagent.evaluation.v2results import analyse, load_groups

ROOT = Path(__file__).resolve().parents[1]


def _pct(x: float) -> str:
    return f"{100 * x:5.1f} %"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results" / "v2")
    ap.add_argument("--min-seeds", type=int, default=1, help="fail if a config has fewer seeds")
    args = ap.parse_args(argv)
    try:
        configs, comparisons = analyse(load_groups(args.results_dir))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not configs:
        print(f"error: no v2 results files in {args.results_dir}", file=sys.stderr)
        return 2
    print("configuration | tasks x seeds | success (95 % CI) | seed min-max | all/some/none")
    for c in configs:
        s, r = c.success, c.reliability
        print(
            f"{c.key.label} | {s.n_tasks} x {s.n_seeds} | {_pct(s.mean)} "
            f"({_pct(s.ci_low)} to {_pct(s.ci_high)}) | {_pct(s.seed_min)} - {_pct(s.seed_max)} "
            f"| {r.all_seeds}/{r.some_seeds}/{r.no_seed}"
        )
    print()
    print("comparison | difference | McNemar seed 0 (a-only/b-only, p)")
    for cmp in comparisons:
        p = cmp.paired
        mc = cmp.mcnemar_seed0
        mc_text = (
            "n/a (no seed 0)" if mc is None else f"{mc.a_only}/{mc.b_only}, p={mc.p_value:.4f}"
        )
        print(
            f"{cmp.a.label} vs {cmp.b.mode} | "
            f"{difference_wording(p.diff, p.ci_low, p.ci_high)} | {mc_text}"
        )
    few = [c.key.label for c in configs if c.success.n_seeds < args.min_seeds]
    if few:
        print(f"error: fewer than {args.min_seeds} seeds: {few}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

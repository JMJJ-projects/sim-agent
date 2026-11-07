"""Write docs/eval_results.md and docs/eval_chart.png from results/*.jsonl (R-EV-7)."""

from __future__ import annotations

from pathlib import Path

from simagent.evaluation.report import write_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    n = write_report(ROOT)
    print(f"wrote docs/eval_results.md ({n} complete runs)")


if __name__ == "__main__":
    main()

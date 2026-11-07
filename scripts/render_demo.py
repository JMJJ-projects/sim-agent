"""Render docs/demo.svg from a real, saved agent run where a repair happened.

    python scripts/render_demo.py                      # pick a repaired run from the benchmark
    python scripts/render_demo.py --run-dir runs/...   # a specific run directory

Nothing is invented: the SVG shows the request, each attempt's saved error report, the final
answer and the final script exactly as the run's artifacts (final.json, trace.json) recorded
them, drawn with the same view as `simagent solve`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from simagent.cli import print_final

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEARCH = ROOT / "runs" / "bench" / "artifacts"
PREFERRED_MODEL = "qwen2.5-coder_3b"


def _load(run_dir: Path) -> dict[str, Any]:
    final: dict[str, Any] = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    final["files"] = dict.fromkeys(final.get("files", []), "")
    return final


def find_repaired_run(search: Path) -> Path | None:
    """A solved run whose first attempt failed.

    Preference order: the primary local model in repair mode, then a typical sandbox time, then
    the shortest final script (fits the SVG). Every candidate is an unmodified recorded run.
    """
    candidates = []
    for final_path in sorted(search.rglob("final.json")):
        final = json.loads(final_path.read_text(encoding="utf-8"))
        errors = final.get("errors") or []
        task = final_path.parent.parent.name
        if task.startswith(("adv_", "ambig_")):
            continue  # the demo shows an ordinary request, not an adversarial/misleading task
        if final.get("status") == "solved" and len(errors) >= 2 and errors[0]:
            preferred = (
                PREFERRED_MODEL in final_path.as_posix() and "-repair" in final_path.as_posix()
            )
            # Prefer a typical run (sandbox time under 10 s) over an outlier; all are real runs.
            typical = (final.get("metrics") or {}).get("run_s", 0) < 10
            candidates.append(
                (
                    not preferred,
                    not typical,
                    len(final.get("final_script") or ""),
                    final_path.parent,
                )
            )
    return min(candidates)[-1] if candidates else None


def render(run_dir: Path, out: Path) -> None:
    final = _load(run_dir)
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    console = Console(record=True, width=100, force_terminal=True, color_system="truecolor")
    console.print(
        f"[dim]$[/] simagent solve {json.dumps(final['request'])} "
        f"--provider {trace.get('provider')} --model {trace.get('model')}",
        highlight=False,
        soft_wrap=True,
    )
    print_final(final, Path(trace["run_dir"]), console=console)  # type: ignore[arg-type]
    console.print(
        f"[dim]recorded run {trace['run_dir']} ({trace.get('started_utc', '')[:19]} UTC)[/]",
        highlight=False,
    )
    out.write_text(console.export_svg(title="simagent solve"), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--search", type=Path, default=DEFAULT_SEARCH)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "demo.svg")
    args = ap.parse_args(argv)
    run_dir = args.run_dir or find_repaired_run(args.search)
    if run_dir is None:
        print(f"no repaired run found under {args.search}", file=sys.stderr)
        return 2
    render(run_dir, args.out)
    print(f"wrote {args.out} from {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Write ``docs/graph.mmd``, the Mermaid diagram of the agent graph."""

from __future__ import annotations

from pathlib import Path

from simagent.graph import mermaid

OUT = Path(__file__).resolve().parents[1] / "docs" / "graph.mmd"


def main() -> None:
    OUT.write_text(mermaid(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

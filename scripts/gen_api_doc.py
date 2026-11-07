"""Write ``docs/api.md``, the compact photonsim API reference given to the model (R-SIM-8)."""

from __future__ import annotations

from pathlib import Path

from photonsim.apidoc import render

OUT = Path(__file__).resolve().parents[1] / "docs" / "api.md"


def main() -> None:
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

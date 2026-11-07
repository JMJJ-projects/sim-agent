"""Build ``src/photonsim/data/materials.json`` from the NIST X-ray mass attenuation tables.

Source: J. H. Hubbell and S. M. Seltzer, "Tables of X-Ray Mass Attenuation Coefficients and
Mass Energy-Absorption Coefficients", NIST Standard Reference Database 126,
https://physics.nist.gov/PhysRefData/XrayMassCoef/ (DOI 10.18434/T4D01F).

For each material the script reads mu/rho and mu_en/rho (cm^2/g) and the density (g/cm^3,
tables 1 and 2), keeps energies in [E_MIN, E_MAX] MeV and writes linear coefficients (cm^-1):

* ``mu_total = rho * (mu/rho)``
* ``mu_abs   = rho * (mu_en/rho)``

Usage::

    python scripts/build_materials.py              # download from NIST
    python scripts/build_materials.py --cache DIR  # use previously downloaded *.html files
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://physics.nist.gov/PhysRefData/XrayMassCoef"
E_MIN, E_MAX = 0.1, 10.0
OUT = Path(__file__).resolve().parents[1] / "src" / "photonsim" / "data" / "materials.json"

# material key -> (table page, name used in the density table)
MATERIALS: dict[str, tuple[str, str]] = {
    "water": ("ComTab/water", "Water, Liquid"),
    "polyethylene": ("ComTab/polyethylene", "Polyethylene"),
    "concrete": ("ComTab/concrete", "Concrete, Ordinary"),
    "aluminium": ("ElemTab/z13", "13"),
    "iron": ("ElemTab/z26", "26"),
    "lead": ("ElemTab/z82", "82"),
}

NUM = re.compile(r"^[0-9]\.[0-9]+E[+-][0-9]+$")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.cells: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "tr":
            self._row = []
        elif t == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "td" and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif t == "tr" and self._row is not None:
            self.cells.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _read(page: str, cache: Path | None) -> str:
    if cache is not None:
        return (cache / f"{page.split('/')[-1]}.html").read_text(encoding="latin-1")
    req = urllib.request.Request(
        f"{BASE_URL}/{page}.html", headers={"User-Agent": "sim-agent-build-materials/0.1"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return str(resp.read().decode("latin-1"))


def parse_coefficients(html: str) -> list[tuple[float, float, float]]:
    """Return (energy MeV, mu/rho, mu_en/rho) triples from a coefficient table page."""
    p = _Text()
    p.feed(html)
    tokens = [t for t in " ".join(p.chunks).split() if NUM.match(t)]
    if len(tokens) % 3 != 0:
        raise ValueError("unexpected table layout: numeric tokens not a multiple of 3")
    rows: list[tuple[float, float, float]] = []
    for i in range(0, len(tokens), 3):
        row = (float(tokens[i]), float(tokens[i + 1]), float(tokens[i + 2]))
        # The page repeats the table (HTML + ASCII); stop when energies start over.
        if rows and row[0] < rows[-1][0]:
            break
        rows.append(row)
    return rows


def parse_density(html: str, name: str) -> float:
    """Return the density (g/cm^3) for ``name`` (material name or atomic number)."""
    p = _Text()
    p.feed(html)
    for row in p.cells:
        if row and row[0].strip() == name:
            return float(row[-1] if name.isdigit() else row[3])
    raise ValueError(f"density for {name!r} not found")


def build(cache: Path | None) -> dict[str, object]:
    tab1, tab2 = _read("tab1", cache), _read("tab2", cache)
    materials: dict[str, object] = {}
    for key, (page, density_name) in MATERIALS.items():
        rho = parse_density(tab1 if density_name.isdigit() else tab2, density_name)
        rows = [r for r in parse_coefficients(_read(page, cache)) if E_MIN <= r[0] <= E_MAX]
        energies = [r[0] for r in rows]
        if len(set(energies)) != len(energies):
            raise ValueError(f"{key}: absorption edge inside [{E_MIN}, {E_MAX}] MeV")
        materials[key] = {
            "density_g_cm3": rho,
            "energy_mev": energies,
            "mu_total": [float(f"{rho * r[1]:.5g}") for r in rows],
            "mu_abs": [float(f"{rho * r[2]:.5g}") for r in rows],
            "source": (
                "NIST SRD 126 (Hubbell & Seltzer), "
                f"{BASE_URL}/{page}.html; density from {BASE_URL}/"
                f"{'tab1' if density_name.isdigit() else 'tab2'}.html. "
                "mu_total = rho*(mu/rho); mu_abs = rho*(mu_en/rho)."
            ),
        }
    return {
        "description": (
            "Linear attenuation coefficients (cm^-1). mu_total from mu/rho, mu_abs from the mass "
            "energy-absorption coefficient mu_en/rho, both times the tabulated density. "
            "Generated by scripts/build_materials.py; do not edit by hand."
        ),
        "units": {"energy_mev": "MeV", "mu_total": "1/cm", "mu_abs": "1/cm"},
        "retrieved": date.today().isoformat(),
        "materials": materials,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=None, help="directory with downloaded pages")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    data = build(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

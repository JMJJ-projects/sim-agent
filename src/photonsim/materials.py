"""Material data loading and log-log interpolation of attenuation coefficients."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class MaterialData:
    """Tabulated linear attenuation coefficients for one material."""

    name: str
    density_g_cm3: float
    energy_mev: FloatArray
    mu_total: FloatArray
    mu_abs: FloatArray
    source: str

    @property
    def energy_range(self) -> tuple[float, float]:
        return float(self.energy_mev[0]), float(self.energy_mev[-1])

    def coefficients(self, energy_mev: float) -> tuple[float, float]:
        """Return ``(mu_total, mu_abs)`` in cm^-1, log-log interpolated at ``energy_mev``."""
        lo, hi = self.energy_range
        if not (isinstance(energy_mev, int | float) and math.isfinite(energy_mev)):
            raise ValueError(f"energy_mev must be a finite number, got {energy_mev!r}")
        if not lo <= energy_mev <= hi:
            raise ValueError(
                f"energy_mev={energy_mev:g} is outside the data range for {self.name!r}: "
                f"valid energies are {lo:g} to {hi:g} MeV"
            )
        log_e = math.log(energy_mev)
        log_tab = np.log(self.energy_mev)
        mu_t = math.exp(float(np.interp(log_e, log_tab, np.log(self.mu_total))))
        mu_a = math.exp(float(np.interp(log_e, log_tab, np.log(self.mu_abs))))
        return mu_t, min(mu_a, mu_t)


def _parse(raw: dict[str, Any]) -> dict[str, MaterialData]:
    out: dict[str, MaterialData] = {}
    for name, entry in raw["materials"].items():
        energy = np.asarray(entry["energy_mev"], dtype=np.float64)
        mu_t = np.asarray(entry["mu_total"], dtype=np.float64)
        mu_a = np.asarray(entry["mu_abs"], dtype=np.float64)
        if not (energy.shape == mu_t.shape == mu_a.shape) or energy.size < 2:
            raise ValueError(f"material {name!r}: inconsistent table lengths")
        if np.any(np.diff(energy) <= 0):
            raise ValueError(f"material {name!r}: energies must be strictly increasing")
        if np.any(mu_t <= 0) or np.any(mu_a <= 0) or np.any(mu_a > mu_t):
            raise ValueError(f"material {name!r}: need 0 < mu_abs <= mu_total")
        if not entry.get("source"):
            raise ValueError(f"material {name!r}: missing 'source'")
        out[name] = MaterialData(
            name=name,
            density_g_cm3=float(entry["density_g_cm3"]),
            energy_mev=energy,
            mu_total=mu_t,
            mu_abs=mu_a,
            source=str(entry["source"]),
        )
    return out


@lru_cache(maxsize=1)
def load_materials() -> dict[str, MaterialData]:
    """Load the bundled material table (``photonsim/data/materials.json``)."""
    text = resources.files("photonsim").joinpath("data/materials.json").read_text("utf-8")
    return _parse(json.loads(text))


def list_materials() -> list[str]:
    """Return the names of all available materials, sorted."""
    return sorted(load_materials())


def get_material(name: str, *, argument: str = "material") -> MaterialData:
    """Look up a material by name (case-insensitive); unknown names raise ``ValueError``."""
    table = load_materials()
    key = name.strip().lower() if isinstance(name, str) else name
    if not isinstance(key, str) or key not in table:
        raise ValueError(
            f"{argument}: unknown material {name!r}. Valid options: {', '.join(sorted(table))}"
        )
    return table[key]


def energy_range(material: str) -> tuple[float, float]:
    """Return ``(min_mev, max_mev)``, the energy range covered by the data for ``material``."""
    return get_material(material).energy_range

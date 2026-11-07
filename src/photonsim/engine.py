"""Simulation engine: input validation and the `simulate` entry point."""

from __future__ import annotations

import math

import numpy as np

from photonsim.geometry import Slab
from photonsim.materials import get_material
from photonsim.result import Result
from photonsim.transport import transport

CHUNK = 1_000_000
MAX_PHOTONS = 50_000_000


def check_n_photons(n_photons: object) -> int:
    """Validate ``n_photons`` and return it as an int."""
    bad = ValueError(f"n_photons must be a whole number >= 1, got {n_photons!r}")
    if isinstance(n_photons, bool):
        raise bad
    if isinstance(n_photons, float):
        if not math.isfinite(n_photons) or not n_photons.is_integer():
            raise bad
        n = int(n_photons)
    elif isinstance(n_photons, int):
        n = n_photons
    else:
        raise bad
    if n < 1:
        raise ValueError(f"n_photons must be >= 1, got {n}")
    if n > MAX_PHOTONS:
        raise ValueError(f"n_photons must be <= {MAX_PHOTONS:_}, got {n:_}")
    return n


def check_seed(seed: object) -> int | None:
    """Validate ``seed`` (None or a non-negative int)."""
    if seed is None:
        return None
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be None or an int >= 0, got {seed!r}")
    return seed


def simulate(slab: Slab, energy_mev: float, n_photons: int, seed: int | None = None) -> Result:
    """Simulate ``n_photons`` photons of ``energy_mev`` MeV hitting ``slab`` at normal incidence.

    The same ``seed`` always gives the same ``Result``. Raises ``ValueError`` for an invalid
    slab, an energy outside a layer material's data range, or ``n_photons < 1``.
    """
    if not isinstance(slab, Slab):
        raise ValueError(
            f"slab must be a Slab([Layer(material, thickness_cm), ...]), got {type(slab).__name__}"
        )
    n = check_n_photons(n_photons)
    seed = check_seed(seed)
    mu_t = np.empty(len(slab.layers))
    mu_a = np.empty(len(slab.layers))
    for i, layer in enumerate(slab.layers):
        mu_t[i], mu_a[i] = get_material(layer.material).coefficients(energy_mev)
    thickness = np.array([layer.thickness_cm for layer in slab.layers])

    rng = np.random.default_rng(seed)
    t = r = a = 0
    remaining = n
    while remaining > 0:
        k = min(CHUNK, remaining)
        tally = transport(thickness, mu_t, mu_a, k, rng)
        t, r, a = t + tally.transmitted, r + tally.reflected, a + tally.absorbed
        remaining -= k
    return Result.from_counts(t, r, a, float(energy_mev))

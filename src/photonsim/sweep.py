"""Parameter sweeps over slab configurations."""

from __future__ import annotations

import math
from collections.abc import Callable

from photonsim.engine import check_n_photons, check_seed, simulate
from photonsim.geometry import Slab
from photonsim.result import Result


def sweep(
    build: Callable[[float], Slab],
    values: list[float],
    energy_mev: float,
    n_photons: int,
    seed: int | None = None,
) -> list[tuple[float, Result]]:
    """Run ``simulate(build(v), energy_mev, n_photons, seed)`` for each ``v`` in ``values``.

    Returns ``[(v, Result), ...]`` in the order of ``values``. With a seed, every point uses the
    same seed (common random numbers), which makes curves smoother and monotonic trends clearer.
    """
    if not callable(build):
        raise ValueError("build must be a function value -> Slab, e.g. lambda t: Slab([...])")
    if isinstance(values, str) or not hasattr(values, "__iter__"):
        raise ValueError(f"values must be a non-empty list of numbers, got {values!r}")
    vals = list(values)
    if not vals:
        raise ValueError("values must be a non-empty list of numbers")
    for v in vals:
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            raise ValueError(f"values must contain finite numbers, got {v!r}")
    check_n_photons(n_photons)
    check_seed(seed)
    out: list[tuple[float, Result]] = []
    for v in vals:
        slab = build(float(v))
        if not isinstance(slab, Slab):
            raise ValueError(f"build({v!r}) must return a Slab, got {type(slab).__name__}")
        out.append((float(v), simulate(slab, energy_mev, n_photons, seed)))
    return out

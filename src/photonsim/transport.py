"""Vectorised Monte Carlo photon transport through a slab stack.

Model (deliberately simplified, see R-SIM-2): mono-energetic photons enter the front face at
normal incidence. Free paths are exponential with the local ``mu_total``. At each interaction a
photon is absorbed with probability ``mu_abs / mu_total``; otherwise it scatters isotropically
with no energy loss. Photons leaving the back face are transmitted, those leaving the front face
are reflected. The loop runs over interaction steps, not over photons.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

MAX_STEPS = 1_000_000


@dataclass(frozen=True)
class Tally:
    """Photon counts by fate."""

    transmitted: int
    reflected: int
    absorbed: int

    @property
    def total(self) -> int:
        return self.transmitted + self.reflected + self.absorbed


def transport(
    thickness_cm: FloatArray,
    mu_total: FloatArray,
    mu_abs: FloatArray,
    n_photons: int,
    rng: np.random.Generator,
) -> Tally:
    """Track ``n_photons`` through layers with the given thicknesses and coefficients (cm^-1)."""
    thickness = np.asarray(thickness_cm, dtype=np.float64)
    mu_t = np.asarray(mu_total, dtype=np.float64)
    p_abs = np.asarray(mu_abs, dtype=np.float64) / mu_t
    n_layers = thickness.size
    edges = np.concatenate(([0.0], np.cumsum(thickness)))

    x = np.zeros(n_photons)
    cos = np.ones(n_photons)
    layer = np.zeros(n_photons, dtype=np.int64)

    transmitted = reflected = absorbed = 0
    for _ in range(MAX_STEPS):
        if x.size == 0:
            break
        # Distance to the boundary the photon is heading for.
        target = np.where(cos > 0, edges[layer + 1], edges[layer])
        with np.errstate(divide="ignore", invalid="ignore"):
            d_boundary = np.where(cos != 0, (target - x) / cos, np.inf)
        d_boundary = np.maximum(d_boundary, 0.0)
        s = rng.exponential(1.0, size=x.size) / mu_t[layer]

        crosses = s >= d_boundary
        # Photons crossing a boundary: move onto it and change layer (memoryless free path).
        x = np.where(crosses, target, x + s * cos)
        layer = np.where(crosses, layer + np.where(cos > 0, 1, -1), layer)

        out_back = crosses & (layer >= n_layers)
        out_front = crosses & (layer < 0)
        transmitted += int(np.count_nonzero(out_back))
        reflected += int(np.count_nonzero(out_front))

        interacts = ~crosses
        u = rng.random(x.size)
        safe_layer = np.clip(layer, 0, n_layers - 1)
        is_absorbed = interacts & (u < p_abs[safe_layer])
        absorbed += int(np.count_nonzero(is_absorbed))

        scatters = interacts & ~is_absorbed
        n_scatter = int(np.count_nonzero(scatters))
        if n_scatter:
            cos = cos.copy()
            cos[scatters] = rng.uniform(-1.0, 1.0, size=n_scatter)

        alive = ~(out_back | out_front | is_absorbed)
        x, cos, layer = x[alive], cos[alive], layer[alive]
    else:  # pragma: no cover - defensive, needs pathological inputs
        raise RuntimeError(f"transport did not finish within {MAX_STEPS} steps")

    return Tally(transmitted=transmitted, reflected=reflected, absorbed=absorbed)

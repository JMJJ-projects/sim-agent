"""Simulation result container."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Result:
    """Outcome of ``simulate``: fractions of photons by fate, summing to 1.

    Attributes:
        transmitted: fraction leaving the back face (includes scattered photons).
        reflected: fraction back-scattered out of the front face.
        absorbed: fraction absorbed inside the slab.
        n_photons: number of photons simulated.
        energy_mev: photon energy in MeV.
        stderr_transmitted: binomial standard error of ``transmitted``.
        stderr_reflected: binomial standard error of ``reflected``.
        stderr_absorbed: binomial standard error of ``absorbed``.
    """

    transmitted: float
    reflected: float
    absorbed: float
    n_photons: int
    energy_mev: float
    stderr_transmitted: float
    stderr_reflected: float
    stderr_absorbed: float

    @classmethod
    def from_counts(
        cls, transmitted: int, reflected: int, absorbed: int, energy_mev: float
    ) -> Result:
        n = transmitted + reflected + absorbed
        if n < 1:
            raise ValueError("Result needs at least one photon")

        def se(k: int) -> float:
            p = k / n
            return math.sqrt(p * (1.0 - p) / n)

        return cls(
            transmitted=transmitted / n,
            reflected=reflected / n,
            absorbed=absorbed / n,
            n_photons=n,
            energy_mev=float(energy_mev),
            stderr_transmitted=se(transmitted),
            stderr_reflected=se(reflected),
            stderr_absorbed=se(absorbed),
        )

    def to_dict(self) -> dict[str, float | int]:
        """Return the result as a JSON-serialisable dict."""
        return asdict(self)

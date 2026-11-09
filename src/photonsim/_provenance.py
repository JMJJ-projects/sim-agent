"""Provenance recorder: what the simulator actually ran (R-TRACE-1, R-TRACE-2).

Recording is on only when the environment variable ``PHOTONSIM_TRACE`` is ``"1"`` when
photonsim is first imported. The sandbox image sets it; generated code cannot (it has no access
to ``os``, and the policy rejects any reference to this module, R-POL-6). ``simagent_io.submit``
writes the snapshot to ``/out/trace.json``.

Each record: ``source`` ("simulate" or "sweep"), ``value`` (the swept value, sweep only),
``layers`` (``[[material, thickness_cm], ...]``, beam side first), ``energy_mev``, ``n_photons``,
``seed``, the three fractions and their standard errors. At most ``MAX_CALLS`` records are kept;
beyond that ``truncated`` is true and ``n_calls`` still counts every call.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from photonsim.geometry import Slab
    from photonsim.result import Result

ENV_FLAG = "PHOTONSIM_TRACE"
MAX_CALLS = 500
TRACE_VERSION = 1


class _Recorder:
    def __init__(self, enabled: bool, max_calls: int = MAX_CALLS) -> None:
        self.enabled = enabled
        self.max_calls = max_calls
        self.calls: list[dict[str, Any]] = []
        self.n_calls = 0

    def record(
        self,
        source: str,
        slab: Slab,
        energy_mev: float,
        n_photons: int,
        seed: int | None,
        result: Result,
        value: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.n_calls += 1
        if len(self.calls) >= self.max_calls:
            return
        entry: dict[str, Any] = {"source": source}
        if value is not None:
            entry["value"] = float(value)
        entry.update(
            {
                "layers": [[layer.material, float(layer.thickness_cm)] for layer in slab.layers],
                "energy_mev": float(energy_mev),
                "n_photons": int(n_photons),
                "seed": seed,
                "transmitted": result.transmitted,
                "reflected": result.reflected,
                "absorbed": result.absorbed,
                "stderr_transmitted": result.stderr_transmitted,
                "stderr_reflected": result.stderr_reflected,
                "stderr_absorbed": result.stderr_absorbed,
            }
        )
        self.calls.append(entry)

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": TRACE_VERSION,
            "enabled": self.enabled,
            "max_calls": self.max_calls,
            "n_calls": self.n_calls,
            "truncated": self.n_calls > len(self.calls),
            "calls": [dict(c) for c in self.calls],
        }


RECORDER = _Recorder(enabled=os.environ.get(ENV_FLAG) == "1")


def reset(enabled: bool, max_calls: int = MAX_CALLS) -> None:
    """Start a fresh recording (tests only; never reachable from generated code)."""
    global RECORDER
    RECORDER = _Recorder(enabled, max_calls)


def recorder() -> _Recorder:
    return RECORDER

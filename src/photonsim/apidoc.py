"""Render the compact API reference given to the model (``docs/api.md``, R-SIM-8)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import photonsim
from photonsim.materials import load_materials

INTRO = """\
# photonsim API reference

`photonsim` is a Monte Carlo simulator of mono-energetic photons hitting a 1D stack of slab
layers at normal incidence. Each photon ends `transmitted` (leaves the back face), `reflected`
(back-scattered out of the front face) or `absorbed`.

Simplified physics: exponential free path from the layer's `mu_total`; at each interaction the
photon is absorbed with probability `mu_abs/mu_total`, else scattered isotropically with no
energy loss. Transmission therefore includes scattered photons. Units: cm, MeV.
"""

EXAMPLE = """\
## Example

```python
import photonsim as ps

slab = ps.Slab([ps.Layer("water", 5.0), ps.Layer("lead", 1.0)])
res = ps.simulate(slab, energy_mev=1.0, n_photons=100_000, seed=1)
print(res.transmitted, res.stderr_transmitted)

curve = ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), [1, 2, 4], 1.0, 20_000, seed=1)
for thickness, r in curve:
    print(thickness, r.transmitted)
```

Invalid arguments raise `ValueError` with a message naming the argument and valid options.
"""


def _sig(name: str, obj: Callable[..., Any]) -> str:
    sig = str(inspect.signature(obj)).replace("'", "")
    if inspect.isclass(obj):
        sig = sig.split(" -> ")[0]
    return f"{name}{sig}"


def _doc(obj: object) -> str:
    return (inspect.getdoc(obj) or "").replace("``", "`")


def render() -> str:
    """Return the API reference as Markdown."""
    parts = [INTRO, "## Materials\n", "| name | energy range (MeV) |", "|---|---|"]
    for name, mat in sorted(load_materials().items()):
        lo, hi = mat.energy_range
        parts.append(f"| `{name}` | {lo:g} to {hi:g} |")
    parts.append("\nData: NIST SRD 126 (Hubbell & Seltzer). Outside the range: `ValueError`.\n")
    parts.append("## Functions and classes\n")
    for name in ["Layer", "Slab", "simulate", "sweep", "list_materials", "energy_range"]:
        obj = getattr(photonsim, name)
        parts.append(f"### `{_sig(name, obj)}`\n\n{_doc(obj)}\n")
    result_doc = _doc(photonsim.Result).replace(
        "Attributes:", "Attributes (all float except `n_photons`):"
    )
    parts.append(f"### `Result`\n\n{result_doc}\n\n`to_dict()` returns these fields as a dict.\n")
    parts.append(EXAMPLE)
    return "\n".join(parts)

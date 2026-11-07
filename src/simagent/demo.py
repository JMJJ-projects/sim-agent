"""Built-in scripted replies for ``--provider fake`` (offline demo, R-LLM-2).

The first reply has a realistic bug (a chemical formula instead of a material name), so the
offline demo shows a full repair cycle: the sandbox raises photonsim's ``ValueError`` listing
the valid materials, and the second reply fixes it. The fake provider ignores the request text;
the demo always simulates 1 MeV photons through 5 cm of water.
"""

DEMO_REQUEST = "transmission of 1 MeV photons through 5 cm of water"

_BUGGY = """\
I build a single 5 cm water slab, simulate 100 000 photons at 1 MeV with a fixed seed and
report the transmitted fraction with its standard error.

```python
import photonsim as ps
import simagent_io

slab = ps.Slab([ps.Layer("H2O", 5.0)])
res = ps.simulate(slab, energy_mev=1.0, n_photons=100_000, seed=1)
print(f"T = {res.transmitted:.4f} +/- {res.stderr_transmitted:.4f}")
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted, result=res)
```
"""

_FIXED = """\
The material name was wrong: photonsim calls it "water", not "H2O". Same simulation otherwise:
5 cm of water, 100 000 photons at 1 MeV, seed 1, reporting the transmitted fraction.

```python
import photonsim as ps
import simagent_io

slab = ps.Slab([ps.Layer("water", 5.0)])
res = ps.simulate(slab, energy_mev=1.0, n_photons=100_000, seed=1)
print(f"T = {res.transmitted:.4f} +/- {res.stderr_transmitted:.4f}")
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted, result=res)
```
"""

DEMO_REPLIES: list[str] = [_BUGGY, _FIXED]

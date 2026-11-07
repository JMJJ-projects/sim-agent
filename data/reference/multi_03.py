import simagent_io

import photonsim as ps

iron = ps.simulate(ps.Slab([ps.Layer("iron", 3.0)]), 1.0, 100000, seed=1)
found = None
for t, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("water", t)]), [float(k) for k in range(1, 61)], 1.0, 20000, seed=2
):
    if r.transmitted <= iron.transmitted:
        found = t
        break
assert found is not None
simagent_io.submit(
    {"iron_transmitted": iron.transmitted, "water_cm": found}, stderr=iron.stderr_transmitted
)

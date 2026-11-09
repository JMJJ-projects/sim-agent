import simagent_io

import photonsim as ps

r_thick = ps.simulate(ps.Slab([ps.Layer("water", 50.0)]), 0.5, 100000, seed=1)
found = None
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("water", t)]), [float(k) for k in range(1, 51)], 0.5, 20000, seed=2
):
    if r.reflected >= 0.5 * r_thick.reflected:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(
    {"r_thick": r_thick.reflected, "thickness_cm": found}, stderr=r_thick.stderr_reflected
)

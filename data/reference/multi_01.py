import simagent_io

import photonsim as ps

found = None
for t, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("lead", t)]), [0.5 * k for k in range(1, 21)], 1.0, 20000, seed=1
):
    if r.transmitted < 0.05:
        found = t
        break
assert found is not None
r = ps.simulate(ps.Slab([ps.Layer("lead", found)]), 1.0, 100000, seed=2)
simagent_io.submit({"thickness_cm": found, "reflected": r.reflected})

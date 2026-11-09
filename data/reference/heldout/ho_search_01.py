import simagent_io

import photonsim as ps

found = None
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("iron", t)]), [0.5 * k for k in range(1, 41)], 1.25, 20000, seed=1
):
    if r.transmitted < 0.02:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

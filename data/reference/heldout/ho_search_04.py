import simagent_io

import photonsim as ps

found = None
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("aluminium", t)]),
    [round(0.2 * k, 1) for k in range(1, 51)],
    2.0,
    20000,
    seed=1,
):
    if r.absorbed > 0.05:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

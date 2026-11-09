import simagent_io

import photonsim as ps

found = None
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("polyethylene", t)]),
    [float(k) for k in range(1, 81)],
    0.15,
    20000,
    seed=1,
):
    if r.absorbed >= 0.40:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

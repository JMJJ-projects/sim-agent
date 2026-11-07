import simagent_io

import photonsim as ps

found = None
for w, r in ps.sweep(
    lambda w: ps.Slab([ps.Layer("lead", 2.0), ps.Layer("water", w)]),
    [float(k) for k in range(1, 81)],
    1.0,
    20000,
    seed=1,
):
    if r.transmitted < 0.02:
        found = w
        break
assert found is not None
simagent_io.submit(found)

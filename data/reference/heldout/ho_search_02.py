import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("lead", 3.0)])
found = None
for e in [0.25 * k for k in range(1, 41)]:
    if ps.simulate(slab, e, 20000, seed=1).transmitted > 0.10:
        found = e
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("iron", 5.0)])
found = None
for e in [0.5 * k for k in range(1, 21)]:
    if ps.simulate(slab, e, 20000, seed=1).transmitted > 0.30:
        found = e
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

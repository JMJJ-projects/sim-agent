import simagent_io

import photonsim as ps

grid = [0.5 * k for k in range(1, 31)]
found = None
for x, r in ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), grid, 1.0, 20000, seed=1):
    if r.transmitted < 0.01:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

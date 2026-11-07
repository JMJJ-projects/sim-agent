import simagent_io

import photonsim as ps

grid = [2.0 * k for k in range(1, 51)]
found = None
for x, r in ps.sweep(lambda t: ps.Slab([ps.Layer("polyethylene", t)]), grid, 2.0, 20000, seed=1):
    if r.transmitted < 0.5:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

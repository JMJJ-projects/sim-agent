import simagent_io

import photonsim as ps

grid = [float(k) for k in range(1, 61)]
found = None
for x, r in ps.sweep(lambda t: ps.Slab([ps.Layer("aluminium", t)]), grid, 0.5, 20000, seed=1):
    if r.absorbed > 0.5:
        found = x
        break
assert found is not None, "no crossing in the grid"
simagent_io.submit(found)

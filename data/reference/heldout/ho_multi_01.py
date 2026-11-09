import simagent_io

import photonsim as ps

grid = [0.5 * k for k in range(1, 41)]
found = {}
for m in ["lead", "iron"]:
    for x, r in ps.sweep(lambda t, m=m: ps.Slab([ps.Layer(m, t)]), grid, 1.0, 20000, seed=1):
        if r.transmitted < 0.10:
            found[m] = x
            break
assert set(found) == {"lead", "iron"}, "no crossing in the grid"
simagent_io.submit({"lead_cm": found["lead"], "iron_cm": found["iron"]})

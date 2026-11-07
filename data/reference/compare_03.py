import simagent_io

import photonsim as ps

shields = {"water": 20.0, "iron": 2.0}
t = {}
for m, x in shields.items():
    t[m] = ps.simulate(ps.Slab([ps.Layer(m, x)]), 1.0, 100000, seed=1).transmitted
simagent_io.submit(max(t, key=t.get), transmitted=t)

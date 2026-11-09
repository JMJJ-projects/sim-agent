import simagent_io

import photonsim as ps

shields = {"concrete": 30.0, "iron": 5.0}
r = {
    m: ps.simulate(ps.Slab([ps.Layer(m, x)]), 0.3, 100000, seed=1).reflected
    for m, x in shields.items()
}
simagent_io.submit(max(r, key=r.get), reflected=r)

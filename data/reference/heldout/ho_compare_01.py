import simagent_io

import photonsim as ps

t = {
    m: ps.simulate(ps.Slab([ps.Layer(m, 6.0)]), 0.8, 50000, seed=1).transmitted
    for m in ["water", "aluminium", "iron"]
}
simagent_io.submit(sorted(t, key=lambda m: -t[m]), transmitted=t)

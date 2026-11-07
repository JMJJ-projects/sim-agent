import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("lead", 2.0)])
t = {e: ps.simulate(slab, e, 50000, seed=1).transmitted for e in [0.5, 1.0, 2.0]}
simagent_io.submit({"best_energy_mev": max(t, key=t.get), "ratio": t[2.0] / t[0.5]})

import simagent_io

import photonsim as ps

wall = ps.Slab([ps.Layer("concrete", 20.0)])
refl = {e: ps.simulate(wall, e, 50000, seed=1).reflected for e in [0.2, 0.5, 1.0, 2.0, 5.0]}
best = max(refl, key=refl.get)
res = ps.simulate(ps.Slab([ps.Layer("concrete", 5.0)]), best, 100000, seed=2)
simagent_io.submit(
    {"energy_mev": best, "transmitted": res.transmitted},
    stderr=res.stderr_transmitted,
    reflected={str(e): r for e, r in refl.items()},
)

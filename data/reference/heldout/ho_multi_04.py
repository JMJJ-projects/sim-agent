import simagent_io

import photonsim as ps

ratio = {}
for x in [2.0, 5.0, 10.0]:
    r = ps.simulate(ps.Slab([ps.Layer("aluminium", x)]), 0.6, 50000, seed=1)
    ratio[x] = r.absorbed / r.reflected
best = max(ratio, key=ratio.get)
simagent_io.submit({"thickness_cm": best, "ratio": ratio[best]})

import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("iron", 1.5)])
pairs, se = [], []
for e in [0.15, 0.3, 0.6, 1.25, 3.0, 8.0]:
    r = ps.simulate(slab, e, 20000, seed=1)
    pairs.append([e, r.absorbed])
    se.append(r.stderr_absorbed)
simagent_io.submit(pairs, se=se)

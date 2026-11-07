import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("iron", t)]), [1.0, 2.0, 3.0, 4.0, 5.0], 2.0, 20000, seed=1
):
    pairs.append([x, r.absorbed])
    se.append(r.stderr_absorbed)
simagent_io.submit(pairs, se=se)

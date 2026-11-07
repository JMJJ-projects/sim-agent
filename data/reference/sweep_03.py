import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("concrete", t)]),
    [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
    0.662,
    20000,
    seed=1,
):
    pairs.append([x, r.reflected])
    se.append(r.stderr_reflected)
simagent_io.submit(pairs, se=se)

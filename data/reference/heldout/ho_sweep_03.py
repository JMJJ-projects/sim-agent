import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("aluminium", t)]),
    [0.5, 1.0, 2.0, 4.0, 8.0, 16.0],
    0.4,
    20000,
    seed=1,
):
    pairs.append([x, r.reflected])
    se.append(r.stderr_reflected)
simagent_io.submit(pairs, se=se)

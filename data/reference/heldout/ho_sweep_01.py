import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("concrete", t)]),
    [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    4.0,
    20000,
    seed=1,
):
    pairs.append([x, r.transmitted])
    se.append(r.stderr_transmitted)
simagent_io.submit(pairs, se=se)

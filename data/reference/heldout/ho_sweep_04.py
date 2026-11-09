import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("lead", 1.0), ps.Layer("water", t)]),
    [5.0, 10.0, 20.0, 40.0],
    1.25,
    20000,
    seed=1,
):
    pairs.append([x, r.transmitted])
    se.append(r.stderr_transmitted)
simagent_io.submit(pairs, se=se)

import simagent_io

import photonsim as ps

pairs, se = [], []
for x, r in ps.sweep(
    lambda t: ps.Slab([ps.Layer("lead", t)]), [0.5, 1.0, 1.5, 2.0, 2.5, 3.0], 1.0, 20000, seed=1
):
    pairs.append([x, r.transmitted])
    se.append(r.stderr_transmitted)
simagent_io.submit(pairs, se=se)

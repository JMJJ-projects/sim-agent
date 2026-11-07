import simagent_io

import photonsim as ps

pairs, se = [], []
for e in [0.2, 0.5, 1.0, 2.0, 5.0, 10.0]:
    r = ps.simulate(ps.Slab([ps.Layer("water", 10.0)]), e, 20000, seed=1)
    pairs.append([e, r.transmitted])
    se.append(r.stderr_transmitted)
simagent_io.submit(pairs, se=se)

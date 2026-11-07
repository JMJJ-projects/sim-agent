import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("water", 2.0)]), 1.0, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

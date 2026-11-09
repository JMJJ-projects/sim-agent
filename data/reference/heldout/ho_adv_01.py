import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("iron", 3.0)]), 1.0, 50000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

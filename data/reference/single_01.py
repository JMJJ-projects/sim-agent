import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("aluminium", 4.0)]), 0.5, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

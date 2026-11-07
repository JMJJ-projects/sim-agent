import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("concrete", 10.0)]), 6.0, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

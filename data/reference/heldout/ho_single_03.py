import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("iron", 12.0)]), 8.0, 100000, seed=1)
simagent_io.submit(100.0 * res.transmitted, stderr=100.0 * res.stderr_transmitted)

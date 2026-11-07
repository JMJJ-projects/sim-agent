import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("lead", 3.0)]), 2.0, 100000, seed=1)
simagent_io.submit(res.absorbed, stderr=res.stderr_absorbed)

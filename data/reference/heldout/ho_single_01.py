import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("polyethylene", 8.0)]), 0.3, 100000, seed=1)
simagent_io.submit(res.absorbed, stderr=res.stderr_absorbed)

import simagent_io

import photonsim as ps

res = ps.simulate(ps.Slab([ps.Layer("water", 20.0)]), 1.0, 100000, seed=1)
simagent_io.submit(res.reflected, stderr=res.stderr_reflected)

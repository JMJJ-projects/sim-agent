import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("lead", 1.0), ps.Layer("aluminium", 4.0), ps.Layer("concrete", 15.0)])
res = ps.simulate(slab, 3.0, 100000, seed=1)
simagent_io.submit(res.reflected, stderr=res.stderr_reflected)

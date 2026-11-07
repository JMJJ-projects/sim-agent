import simagent_io

import photonsim as ps

out, se = {}, {}
for m in ["lead", "iron"]:
    r = ps.simulate(ps.Slab([ps.Layer(m, 5.0)]), 1.0, 50000, seed=1)
    out[m] = r.transmitted
    se[m] = r.stderr_transmitted
simagent_io.submit(out, stderr=se)

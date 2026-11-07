import simagent_io

import photonsim as ps

res = ps.simulate(
    ps.Slab([ps.Layer("iron", 2.0), ps.Layer("polyethylene", 5.0)]), 1.25, 100000, seed=1
)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

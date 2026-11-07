import simagent_io

import photonsim as ps

# 25 mm = 2.5 cm
res = ps.simulate(ps.Slab([ps.Layer("lead", 2.5)]), 1.0, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

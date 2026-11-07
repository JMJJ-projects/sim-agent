import simagent_io

import photonsim as ps

# 662 keV = 0.662 MeV
res = ps.simulate(ps.Slab([ps.Layer("water", 10.0)]), 0.662, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

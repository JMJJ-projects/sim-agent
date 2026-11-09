import simagent_io

import photonsim as ps

# 1.5 inches = 3.81 cm; 800 keV = 0.8 MeV
res = ps.simulate(ps.Slab([ps.Layer("iron", 1.5 * 2.54)]), 0.8, 100000, seed=1)
simagent_io.submit(res.transmitted, stderr=res.stderr_transmitted)

import math

import simagent_io

import photonsim as ps

alone = ps.simulate(ps.Slab([ps.Layer("water", 20.0)]), 1.25, 100000, seed=1)
lined = ps.simulate(ps.Slab([ps.Layer("lead", 1.0), ps.Layer("water", 20.0)]), 1.25, 100000, seed=2)
diff = alone.transmitted - lined.transmitted
se = math.sqrt(alone.stderr_transmitted**2 + lined.stderr_transmitted**2)
simagent_io.submit(diff, stderr=se)

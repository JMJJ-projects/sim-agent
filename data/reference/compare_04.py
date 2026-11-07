import math

import simagent_io

import photonsim as ps

slab = ps.Slab([ps.Layer("lead", 5.0)])
r1 = ps.simulate(slab, 1.0, 100000, seed=1)
r2 = ps.simulate(slab, 2.0, 100000, seed=2)
ratio = r2.transmitted / r1.transmitted
se = ratio * math.sqrt(
    (r1.stderr_transmitted / r1.transmitted) ** 2 + (r2.stderr_transmitted / r2.transmitted) ** 2
)
simagent_io.submit(ratio, stderr=se)

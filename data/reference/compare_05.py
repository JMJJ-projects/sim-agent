import math

import simagent_io

import photonsim as ps

a = ps.simulate(ps.Slab([ps.Layer("aluminium", 10.0)]), 0.662, 100000, seed=1)
p = ps.simulate(ps.Slab([ps.Layer("polyethylene", 10.0)]), 0.662, 100000, seed=2)
se = math.sqrt(a.stderr_absorbed**2 + p.stderr_absorbed**2)
simagent_io.submit(a.absorbed - p.absorbed, stderr=se)

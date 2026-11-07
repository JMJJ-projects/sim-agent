import simagent_io

import photonsim as ps

lead, water = ps.Layer("lead", 2.0), ps.Layer("water", 10.0)
stacks = {"lead_first": [lead, water], "water_first": [water, lead]}
out, se = {}, {}
for name, layers in stacks.items():
    r = ps.simulate(ps.Slab(layers), 1.0, 50000, seed=1)
    out[name] = r.reflected
    se[name] = r.stderr_reflected
simagent_io.submit(out, stderr=se)

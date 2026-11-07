import math

import numpy as np
import simagent_io

import photonsim as ps

xs = [1.0, 2.0, 3.0, 4.0, 5.0]
ts = [
    r.transmitted
    for _, r in ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), xs, 1.0, 50000, seed=1)
]
slope = np.polyfit(xs, [math.log(t) for t in ts], 1)[0]
simagent_io.submit(float(-slope))

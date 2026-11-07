import simagent_io

import photonsim as ps

lo, hi = ps.energy_range("lead")
assert not lo <= 20.0 <= hi
simagent_io.submit(None, error=f"20 MeV is outside the lead data range ({lo} to {hi} MeV)")

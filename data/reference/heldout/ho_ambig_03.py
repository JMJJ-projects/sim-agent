import simagent_io

import photonsim as ps

lo, hi = ps.energy_range("aluminium")
assert not lo <= 0.05 <= hi
simagent_io.submit(None, error=f"50 keV is outside the aluminium data range ({lo} to {hi} MeV)")

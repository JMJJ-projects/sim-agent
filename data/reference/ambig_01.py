import simagent_io

import photonsim as ps

if "unobtainium" in ps.list_materials():
    raise SystemExit("unexpected: unobtainium exists")
simagent_io.submit(
    None,
    error="unobtainium is not an available material; available: " + ", ".join(ps.list_materials()),
)

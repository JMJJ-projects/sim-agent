import simagent_io

import photonsim as ps

assert "tungsten" not in ps.list_materials()
simagent_io.submit(
    None,
    error="tungsten is not an available material; available: " + ", ".join(ps.list_materials()),
)

import simagent_io

import photonsim as ps

assert "stainless steel" not in ps.list_materials()
simagent_io.submit(
    None,
    error=(
        "stainless steel is not an available material (iron is, but it is not the same "
        "material); available: " + ", ".join(ps.list_materials())
    ),
)

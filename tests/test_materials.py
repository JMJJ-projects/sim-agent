"""Tests for material data and interpolation."""

import math
from typing import Any

import pytest

from photonsim import materials as m


def test_every_material_has_a_cited_or_illustrative_source() -> None:
    """Covers R-SIM-3."""
    for mat in m.load_materials().values():
        assert "NIST" in mat.source or "illustrative" in mat.source.lower()


def test_expected_materials_present() -> None:
    names = m.list_materials()
    assert names == sorted(names)
    for name in ["water", "lead", "iron", "aluminium", "concrete", "polyethylene"]:
        assert name in names


def test_interpolation_hits_table_points() -> None:
    """Covers R-SIM-3."""
    lead = m.get_material("lead")
    for e, mu_t, mu_a in zip(lead.energy_mev, lead.mu_total, lead.mu_abs, strict=True):
        got_t, got_a = lead.coefficients(float(e))
        assert got_t == pytest.approx(mu_t, rel=1e-12)
        assert got_a == pytest.approx(mu_a, rel=1e-12)


def test_interpolation_is_log_log() -> None:
    """Covers R-SIM-3: the midpoint in log E is the geometric mean of the neighbours."""
    water = m.get_material("water")
    e0, e1 = float(water.energy_mev[3]), float(water.energy_mev[4])
    mid = math.sqrt(e0 * e1)
    expected = math.sqrt(float(water.mu_total[3]) * float(water.mu_total[4]))
    assert water.coefficients(mid)[0] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("energy", [0.01, 50.0, float("nan"), float("inf")])
def test_energy_outside_table_raises(energy: float) -> None:
    """Covers R-SIM-3."""
    with pytest.raises(ValueError, match="energy_mev"):
        m.get_material("water").coefficients(energy)


def test_energy_range() -> None:
    lo, hi = m.energy_range("iron")
    assert lo < 1.0 < hi


def test_unknown_material_names_valid_options() -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match="unknown material 'unobtainium'") as exc:
        m.get_material("unobtainium")
    assert "lead" in str(exc.value)
    assert "water" in str(exc.value)


def test_lookup_is_case_insensitive() -> None:
    assert m.get_material(" Lead ").name == "lead"


def _table(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "density_g_cm3": 1.0,
        "energy_mev": [1.0, 2.0],
        "mu_total": [0.2, 0.1],
        "mu_abs": [0.1, 0.05],
        "source": "illustrative",
    }
    entry.update(overrides)
    return {"materials": {"x": entry}}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"mu_total": [0.2]}, "inconsistent"),
        ({"energy_mev": [2.0, 1.0]}, "increasing"),
        ({"mu_abs": [0.3, 0.05]}, "mu_abs <= mu_total"),
        ({"source": ""}, "source"),
    ],
)
def test_parse_rejects_bad_tables(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        m._parse(_table(**overrides))


def test_parse_accepts_valid_table() -> None:
    assert m._parse(_table())["x"].energy_range == (1.0, 2.0)

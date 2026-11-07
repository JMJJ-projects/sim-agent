"""Tests for Layer and Slab validation."""

from typing import Any

import pytest

from photonsim.geometry import Layer, Slab


def test_layer_normalises_material_and_thickness() -> None:
    layer = Layer("Lead", 2)
    assert layer.material == "lead"
    assert layer.thickness_cm == 2.0
    assert isinstance(layer.thickness_cm, float)


def test_unknown_material_lists_options() -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match=r"Layer\.material: unknown material 'aluminum'") as exc:
        Layer("aluminum", 1.0)
    assert "aluminium" in str(exc.value)


@pytest.mark.parametrize("thickness", [0, -1.0, float("nan"), float("inf"), "2", True, None])
def test_bad_thickness_rejected(thickness: Any) -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match=r"Layer\.thickness_cm"):
        Layer("water", thickness)


def test_slab_total_thickness() -> None:
    slab = Slab([Layer("water", 1.5), Layer("lead", 0.5)])
    assert slab.total_thickness_cm == pytest.approx(2.0)


def test_slab_accepts_tuple() -> None:
    assert len(Slab((Layer("iron", 1.0),)).layers) == 1  # type: ignore[arg-type]


def test_empty_slab_rejected() -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match=r"Slab\.layers must be a non-empty list"):
        Slab([])


def test_single_layer_not_in_list_rejected() -> None:
    with pytest.raises(ValueError, match="single Layer"):
        Slab(Layer("water", 1.0))  # type: ignore[arg-type]


def test_non_layer_item_rejected() -> None:
    with pytest.raises(ValueError, match=r"Slab\.layers\[1\]"):
        Slab([Layer("water", 1.0), ("lead", 2.0)])  # type: ignore[list-item]

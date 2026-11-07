"""Slab geometry: Layer and Slab."""

from __future__ import annotations

import math
from dataclasses import dataclass

from photonsim.materials import get_material


@dataclass(frozen=True)
class Layer:
    """One homogeneous slab layer.

    Args:
        material: material name, one of ``list_materials()`` (case-insensitive).
        thickness_cm: layer thickness in cm, > 0.
    """

    material: str
    thickness_cm: float

    def __post_init__(self) -> None:
        mat = get_material(self.material, argument="Layer.material")
        object.__setattr__(self, "material", mat.name)
        t = self.thickness_cm
        if isinstance(t, bool) or not isinstance(t, int | float) or not math.isfinite(t):
            raise ValueError(f"Layer.thickness_cm must be a finite number > 0, got {t!r}")
        if t <= 0:
            raise ValueError(f"Layer.thickness_cm must be > 0 (in cm), got {t!r}")
        object.__setattr__(self, "thickness_cm", float(t))


@dataclass(frozen=True)
class Slab:
    """A stack of layers; photons enter the first layer at normal incidence.

    Args:
        layers: non-empty list of ``Layer``, front (beam side) first.
    """

    layers: list[Layer]

    def __post_init__(self) -> None:
        layers = self.layers
        if isinstance(layers, Layer):
            raise ValueError("Slab.layers must be a list of Layer, got a single Layer; use [layer]")
        if not isinstance(layers, list | tuple) or len(layers) == 0:
            raise ValueError("Slab.layers must be a non-empty list of Layer")
        for i, layer in enumerate(layers):
            if not isinstance(layer, Layer):
                raise ValueError(
                    f"Slab.layers[{i}] must be a Layer(material, thickness_cm), "
                    f"got {type(layer).__name__}"
                )
        object.__setattr__(self, "layers", list(layers))

    @property
    def total_thickness_cm(self) -> float:
        """Sum of the layer thicknesses in cm."""
        return sum(layer.thickness_cm for layer in self.layers)

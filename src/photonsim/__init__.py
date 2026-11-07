"""photonsim: a small vectorised Monte Carlo photon-transport simulator for 1D slab stacks.

Public API: ``Layer``, ``Slab``, ``simulate``, ``Result``, ``sweep``, ``list_materials``,
``energy_range``. Physics is deliberately simplified (see ``photonsim.transport``).
"""

from photonsim.engine import simulate
from photonsim.geometry import Layer, Slab
from photonsim.materials import energy_range, list_materials
from photonsim.result import Result
from photonsim.sweep import sweep

__all__ = ["Layer", "Result", "Slab", "energy_range", "list_materials", "simulate", "sweep"]

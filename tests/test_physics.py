"""Physics validation and invariants of the simulator."""

import itertools
import math
import time

import numpy as np
import pytest

import photonsim as p
import photonsim.engine as engine
from photonsim.materials import MaterialData, get_material
from photonsim.transport import transport

N = 50_000


def _within(measured: float, expected: float, n: int, k: float = 4.0) -> bool:
    se = math.sqrt(expected * (1.0 - expected) / n)
    return abs(measured - expected) <= k * max(se, 1.0 / n)


@pytest.mark.parametrize("thickness", [0.5, 1.0, 2.0, 4.0, 8.0])
def test_beer_lambert_pure_absorber_kernel(thickness: float) -> None:
    """Covers R-SIM-7: with mu_abs == mu_total, T = exp(-mu x) within 4 standard errors."""
    mu, _ = get_material("lead").coefficients(1.0)
    tally = transport(
        np.array([thickness]), np.array([mu]), np.array([mu]), N, np.random.default_rng(11)
    )
    assert _within(tally.transmitted / N, math.exp(-mu * thickness), N)


def test_beer_lambert_multilayer_pure_absorber() -> None:
    """Covers R-SIM-7 for a stack: T = exp(-sum mu_i x_i)."""
    t = np.array([2.0, 1.0, 3.0])
    mu = np.array([0.07, 0.8, 0.15])
    tally = transport(t, mu, mu, N, np.random.default_rng(5))
    assert _within(tally.transmitted / N, math.exp(-float(mu @ t)), N)


def test_beer_lambert_through_simulate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-SIM-7 through the public API, with an illustrative pure absorber."""
    lead = get_material("lead")
    absorber = MaterialData(
        name="lead",
        density_g_cm3=lead.density_g_cm3,
        energy_mev=lead.energy_mev,
        mu_total=lead.mu_total,
        mu_abs=lead.mu_total,
        source="illustrative: lead with all interactions treated as absorption",
    )
    monkeypatch.setattr(engine, "get_material", lambda name: absorber)
    mu = absorber.coefficients(2.0)[0]
    for x in [1.0, 3.0, 6.0]:
        res = p.simulate(p.Slab([p.Layer("lead", x)]), 2.0, N, seed=21)
        assert res.reflected == 0.0
        assert _within(res.transmitted, math.exp(-mu * x), N)


def test_scattering_adds_transmission_above_narrow_beam() -> None:
    """With scattering, transmission exceeds exp(-mu_total x) (build-up)."""
    mu, _ = get_material("water").coefficients(1.0)
    res = p.simulate(p.Slab([p.Layer("water", 20.0)]), 1.0, N, seed=2)
    narrow = math.exp(-mu * 20.0)
    assert res.transmitted > narrow + 4 * res.stderr_transmitted


@pytest.mark.parametrize("energy", [0.1, 0.5, 1.0, 5.0, 10.0])
def test_fractions_sum_to_one(energy: float) -> None:
    slab = p.Slab([p.Layer("water", 5.0), p.Layer("lead", 0.5), p.Layer("concrete", 3.0)])
    res = p.simulate(slab, energy, 10_000, seed=3)
    assert res.transmitted + res.reflected + res.absorbed == pytest.approx(1.0, abs=1e-12)
    assert min(res.transmitted, res.reflected, res.absorbed) >= 0.0


def test_same_seed_identical_result() -> None:
    """Covers R-SIM-6."""
    slab = p.Slab([p.Layer("iron", 3.0), p.Layer("polyethylene", 4.0)])
    assert p.simulate(slab, 0.6, 20_000, seed=42) == p.simulate(slab, 0.6, 20_000, seed=42)
    assert p.simulate(slab, 0.6, 20_000, seed=42) != p.simulate(slab, 0.6, 20_000, seed=43)


def test_transmission_decreases_with_thickness() -> None:
    out = p.sweep(lambda t: p.Slab([p.Layer("lead", t)]), [0.5, 1, 2, 4, 8], 1.0, N, seed=8)
    trans = [r.transmitted for _, r in out]
    assert all(a > b for a, b in itertools.pairwise(trans))


def test_thin_slab_transmits_almost_everything() -> None:
    res = p.simulate(p.Slab([p.Layer("water", 1e-4)]), 1.0, N, seed=1)
    assert res.transmitted > 0.999


def test_layer_order_matters_for_reflection() -> None:
    """A low-Z scatterer in front reflects more than the same scatterer behind lead."""
    water, lead = p.Layer("water", 10.0), p.Layer("lead", 5.0)
    front = p.simulate(p.Slab([water, lead]), 1.0, N, seed=4)
    back = p.simulate(p.Slab([lead, water]), 1.0, N, seed=4)
    assert front.reflected > back.reflected + 4 * front.stderr_reflected


@pytest.mark.slow
def test_performance_100k_photons_three_layers() -> None:
    """Covers R-SIM-6: 1e5 photons through a 3-layer slab in under 2 s."""
    slab = p.Slab([p.Layer("water", 10.0), p.Layer("iron", 2.0), p.Layer("concrete", 10.0)])
    p.simulate(slab, 1.0, 1_000, seed=0)  # warm-up
    start = time.perf_counter()
    p.simulate(slab, 1.0, 100_000, seed=0)
    assert time.perf_counter() - start < 2.0

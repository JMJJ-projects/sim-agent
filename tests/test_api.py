"""Tests for the public photonsim API."""

import json
from typing import Any

import pytest

import photonsim as p


def _slab(t: float = 2.0) -> p.Slab:
    return p.Slab([p.Layer("lead", t)])


def test_public_api_names() -> None:
    """Covers R-SIM-4."""
    for name in ["Layer", "Slab", "simulate", "Result", "sweep", "list_materials", "energy_range"]:
        assert hasattr(p, name)


def test_simulate_returns_result() -> None:
    """Covers R-SIM-4."""
    res = p.simulate(_slab(), 1.0, 5_000, seed=1)
    assert isinstance(res, p.Result)
    assert res.n_photons == 5_000
    assert res.transmitted + res.reflected + res.absorbed == pytest.approx(1.0)
    se = (res.transmitted * (1 - res.transmitted) / res.n_photons) ** 0.5
    assert res.stderr_transmitted == pytest.approx(se)


def test_to_dict_is_json_serialisable() -> None:
    """Covers R-SIM-4."""
    d = p.simulate(_slab(), 1.0, 1_000, seed=1).to_dict()
    assert set(d) >= {"transmitted", "reflected", "absorbed", "n_photons", "stderr_transmitted"}
    json.dumps(d)


def test_float_photon_count_accepted_when_integral() -> None:
    assert p.simulate(_slab(), 1.0, 1e3, seed=1).n_photons == 1000  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [0, -5, 10.5, True, "100", float("nan"), 10**9])
def test_bad_photon_count(n: Any) -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match="n_photons"):
        p.simulate(_slab(), 1.0, n)


@pytest.mark.parametrize("seed", [-1, 1.5, "x", True])
def test_bad_seed(seed: Any) -> None:
    with pytest.raises(ValueError, match="seed"):
        p.simulate(_slab(), 1.0, 10, seed=seed)


def test_energy_outside_range() -> None:
    """Covers R-SIM-3."""
    with pytest.raises(ValueError, match="energy_mev=50"):
        p.simulate(_slab(), 50.0, 10)


def test_slab_must_be_slab() -> None:
    with pytest.raises(ValueError, match="slab must be a Slab"):
        p.simulate([p.Layer("lead", 1.0)], 1.0, 10)  # type: ignore[arg-type]


def test_chunking_matches_photon_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import photonsim.engine as sim

    monkeypatch.setattr(sim, "CHUNK", 300)
    res = p.simulate(_slab(), 1.0, 1_000, seed=3)
    assert res.n_photons == 1_000


def test_sweep_order_and_values() -> None:
    """Covers R-SIM-4."""
    out = p.sweep(lambda t: p.Slab([p.Layer("water", t)]), [1, 5, 10], 1.0, 2_000, seed=4)
    assert [v for v, _ in out] == [1.0, 5.0, 10.0]
    assert all(isinstance(r, p.Result) for _, r in out)


def test_sweep_uses_same_seed_per_point() -> None:
    def build(t: float) -> p.Slab:
        return p.Slab([p.Layer("iron", t)])

    out = p.sweep(build, [3.0], 1.0, 2_000, seed=9)
    assert out[0][1] == p.simulate(build(3.0), 1.0, 2_000, seed=9)


@pytest.mark.parametrize(
    ("build", "values", "message"),
    [
        ("not callable", [1.0], "build must be a function"),
        (lambda t: p.Slab([p.Layer("lead", t)]), [], "non-empty"),
        (lambda t: p.Slab([p.Layer("lead", t)]), "123", "non-empty list"),
        (lambda t: p.Slab([p.Layer("lead", t)]), 5, "non-empty list"),
        (lambda t: p.Slab([p.Layer("lead", t)]), [1.0, "x"], "finite numbers"),
        (lambda t: p.Layer("lead", t), [1.0], "must return a Slab"),
    ],
)
def test_sweep_validation(build: Any, values: Any, message: str) -> None:
    """Covers R-SIM-5."""
    with pytest.raises(ValueError, match=message):
        p.sweep(build, values, 1.0, 100)


def test_list_materials_and_energy_range() -> None:
    assert "lead" in p.list_materials()
    lo, hi = p.energy_range("lead")
    assert lo <= 1.0 <= hi


def test_result_needs_photons() -> None:
    with pytest.raises(ValueError, match="at least one photon"):
        p.Result.from_counts(0, 0, 0, 1.0)

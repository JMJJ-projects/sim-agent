"""photonsim's provenance recorder (R-TRACE-1, R-TRACE-2), outside Docker."""

from collections.abc import Iterator

import pytest

import photonsim as ps
from photonsim import _provenance


@pytest.fixture
def recording() -> Iterator[None]:
    _provenance.reset(enabled=True)
    yield
    _provenance.reset(enabled=False)


def test_off_unless_the_flag_was_set_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-TRACE-1: the switch is the environment at import time, not a later change."""
    _provenance.reset(enabled=False)
    monkeypatch.setenv(_provenance.ENV_FLAG, "1")  # too late: read once at import
    ps.simulate(ps.Slab([ps.Layer("water", 1.0)]), 1.0, 100, seed=1)
    snap = _provenance.recorder().snapshot()
    assert snap["enabled"] is False
    assert snap["calls"] == []


def test_simulate_is_recorded(recording: None) -> None:
    """Covers R-TRACE-1: slab, energy, photons, seed and the resulting fractions."""
    slab = ps.Slab([ps.Layer("lead", 1.0), ps.Layer("Water", 5.0)])
    res = ps.simulate(slab, 1.25, 2000, seed=7)
    snap = _provenance.recorder().snapshot()
    assert snap["n_calls"] == 1
    assert snap["truncated"] is False
    call = snap["calls"][0]
    assert call == {
        "source": "simulate",
        "layers": [["lead", 1.0], ["water", 5.0]],
        "energy_mev": 1.25,
        "n_photons": 2000,
        "seed": 7,
        "transmitted": res.transmitted,
        "reflected": res.reflected,
        "absorbed": res.absorbed,
        "stderr_transmitted": res.stderr_transmitted,
        "stderr_reflected": res.stderr_reflected,
        "stderr_absorbed": res.stderr_absorbed,
    }


def test_sweep_records_each_point_with_its_value(recording: None) -> None:
    curve = ps.sweep(lambda t: ps.Slab([ps.Layer("iron", t)]), [1, 2.5], 2.0, 500, seed=None)
    calls = _provenance.recorder().snapshot()["calls"]
    assert [(c["source"], c["value"], c["layers"]) for c in calls] == [
        ("sweep", 1.0, [["iron", 1.0]]),
        ("sweep", 2.5, [["iron", 2.5]]),
    ]
    assert [c["transmitted"] for c in calls] == [r.transmitted for _, r in curve]
    assert calls[0]["seed"] is None


def test_failed_calls_are_not_recorded(recording: None) -> None:
    with pytest.raises(ValueError, match="outside the data range"):
        ps.simulate(ps.Slab([ps.Layer("lead", 1.0)]), 20.0, 100)
    assert _provenance.recorder().snapshot()["n_calls"] == 0


def test_trace_is_capped() -> None:
    """Covers R-TRACE-2: at most max_calls records, truncated beyond, every call counted."""
    _provenance.reset(enabled=True, max_calls=3)
    try:
        slab = ps.Slab([ps.Layer("water", 1.0)])
        for seed in range(5):
            ps.simulate(slab, 1.0, 10, seed=seed)
        snap = _provenance.recorder().snapshot()
    finally:
        _provenance.reset(enabled=False)
    assert len(snap["calls"]) == 3
    assert snap["n_calls"] == 5
    assert snap["truncated"] is True
    assert [c["seed"] for c in snap["calls"]] == [0, 1, 2]
    assert _provenance.MAX_CALLS == 500


def test_snapshot_is_a_copy(recording: None) -> None:
    ps.simulate(ps.Slab([ps.Layer("water", 1.0)]), 1.0, 10, seed=1)
    snap = _provenance.recorder().snapshot()
    snap["calls"][0]["energy_mev"] = 99.0
    assert _provenance.recorder().snapshot()["calls"][0]["energy_mev"] == 1.0

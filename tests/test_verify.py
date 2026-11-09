"""Deterministic verification checks on synthetic traces (R-VER-1, R-VER-2).

The requests here are written for these tests (not taken from the task sets). Each check has a
case where it must fire and one where it must stay silent.
"""

from typing import Any

import pytest

from simagent.request_facts import extract
from simagent.verify import Finding, failures, feedback, verify


def call(
    layers: list[tuple[str, float]],
    energy: float = 1.0,
    n: int = 1000,
    seed: int | None = 1,
    t: float = 0.5,
    r: float = 0.1,
    se: float = 0.01,
    source: str = "simulate",
) -> dict[str, Any]:
    return {
        "source": source,
        "layers": [[m, x] for m, x in layers],
        "energy_mev": energy,
        "n_photons": n,
        "seed": seed,
        "transmitted": t,
        "reflected": r,
        "absorbed": round(1 - t - r, 12),
        "stderr_transmitted": se,
        "stderr_reflected": se,
        "stderr_absorbed": se,
    }


def trace(*calls: dict[str, Any], truncated: bool = False) -> dict[str, Any]:
    return {"version": 1, "calls": list(calls), "n_calls": len(calls), "truncated": truncated}


def checks(request: str, answer: Any, tr: dict[str, Any] | None) -> list[str]:
    return [f.check for f in verify(extract(request), {"answer": answer, "data": {}}, tr)]


SINGLE = "Fraction of 2 MeV photons transmitted by 4 cm of iron? Use 5000 photons."


def test_correct_single_run_passes() -> None:
    tr = trace(call([("iron", 4.0)], energy=2.0, n=5000, t=0.31))
    assert checks(SINGLE, 0.31, tr) == []


def test_v_range() -> None:
    tr = trace(call([("iron", 4.0)], energy=2.0, n=5000, t=0.31))
    assert "V-RANGE" in checks(SINGLE, 31.0, tr)
    pct = "What percentage of 2 MeV photons get through 4 cm of iron? Use 5000 photons."
    assert "V-RANGE" not in checks(pct, 31.0, trace(call([("iron", 4.0)], 2.0, 5000, t=0.31)))
    assert "V-RANGE" in checks(pct, 131.0, None)  # runs without a trace
    sweep = "Transmission of 1 MeV photons for 2, 4 and 6 cm of lead, 1000 photons each."
    assert "V-RANGE" in checks(sweep, [[2, 0.5], [4, 1.2], [6, 0.1]], None)
    ratio = "Ratio of the transmission at 2 MeV to that at 1 MeV for 3 cm of lead."
    assert "V-RANGE" not in checks(ratio, 1.7, None)  # derived quantity: not a fraction


def test_v_energy() -> None:
    wrong = trace(call([("iron", 4.0)], energy=1.0, n=5000, t=0.31))
    assert "V-ENERGY" in checks(SINGLE, 0.31, wrong)
    kev = "Transmitted share of 750 keV photons through 4 cm of iron, 5000 photons."
    ok = trace(call([("iron", 4.0)], energy=0.75, n=5000, t=0.2))
    assert "V-ENERGY" not in checks(kev, 0.2, ok)
    scan = "Transmission through 1 cm of lead from 0.5 to 2 MeV in 0.5 MeV steps, 1000 photons."
    in_range = trace(*(call([("lead", 1.0)], energy=e) for e in (0.5, 1.0, 1.5, 2.0)))
    assert "V-ENERGY" not in checks(scan, [[0.5, 0.1]], in_range)
    outside = trace(call([("lead", 1.0)], energy=3.0))
    assert "V-ENERGY" in checks(scan, [[3.0, 0.1]], outside)


def test_v_length() -> None:
    mm = "Transmitted fraction of 1 MeV photons through 15 mm of lead, 1000 photons."
    assert "V-LENGTH" not in checks(mm, 0.5, trace(call([("lead", 1.5)])))
    findings = verify(extract(mm), {"answer": 0.5}, trace(call([("lead", 15.0)])))
    msgs = [f.message for f in findings if f.check == "V-LENGTH"]
    assert any("1.5 cm" in m for m in msgs)  # the stated thickness is missing
    assert any("15 cm" in m for m in msgs)  # and an unstated one was simulated


def test_v_count() -> None:
    assert "V-COUNT" in checks(SINGLE, 0.31, trace(call([("iron", 4.0)], 2.0, n=1000, t=0.31)))
    loose = "Fraction of 2 MeV photons transmitted by 4 cm of iron?"
    assert "V-COUNT" not in checks(loose, 0.31, trace(call([("iron", 4.0)], 2.0, n=1000, t=0.31)))


def test_v_material() -> None:
    tr = trace(call([("lead", 4.0)], energy=2.0, n=5000, t=0.31))
    found = checks(SINGLE, 0.31, tr)
    assert found.count("V-MATERIAL") == 2  # iron missing, lead not asked for
    alias = "Transmitted share of 1 MeV photons through 5 cm of aluminum, 1000 photons."
    assert "V-MATERIAL" not in checks(alias, 0.5, trace(call([("aluminium", 5.0)])))


def test_v_unknown() -> None:
    unknown = "How much of a 1 MeV beam gets through 2 cm of osmium? Use 1000 photons."
    assert "V-UNKNOWN" in checks(unknown, 0.4, trace(call([("lead", 2.0)])))
    assert "V-UNKNOWN" not in checks(unknown, None, trace())
    too_high = "Transmitted fraction of 30 MeV photons through 2 cm of iron, 1000 photons."
    assert "V-UNKNOWN" in checks(too_high, 0.4, None)  # runs without a trace
    assert "V-UNKNOWN" not in checks(SINGLE, 0.31, None)


SWEEP = "Transmission of 1 MeV photons through 1, 2, 3 and 4 cm of iron, 1000 photons each."


def test_v_sweep_stacked_and_collapsed() -> None:
    stacked = trace(call([("iron", 1.0), ("iron", 2.0), ("iron", 3.0), ("iron", 4.0)]))
    assert "V-SWEEP" in checks(SWEEP, [[1, 0.1]], stacked)
    collapsed = trace(call([("iron", 1.0)]), call([("iron", 1.0)]))
    assert "V-SWEEP" in checks(SWEEP, [[1, 0.1]], collapsed)
    good = trace(*(call([("iron", x)], source="sweep") for x in (1.0, 2.0, 3.0, 4.0)))
    assert "V-SWEEP" not in checks(SWEEP, [[1, 0.5]], good)


def test_v_sweep_allows_searches_to_stop_early() -> None:
    search = (
        "Find the thinnest iron slab, from 1 to 10 cm in 1 cm steps, that lets less than "
        "60 % of 1 MeV photons through. 1000 photons per point."
    )
    early = trace(call([("iron", 1.0)], t=0.7), call([("iron", 2.0)], t=0.55))
    assert "V-SWEEP" not in checks(search, 2.0, early)


def test_v_monotone_is_a_warning() -> None:
    rising = trace(
        call([("iron", 1.0)], t=0.6, se=0.005),
        call([("iron", 2.0)], t=0.8, se=0.005),
        call([("iron", 3.0)], t=0.3, se=0.005),
    )
    findings = verify(extract(SWEEP), {"answer": [[1, 0.6]]}, rising)
    mono = [f for f in findings if f.check == "V-MONOTONE"]
    assert len(mono) == 1
    assert mono[0].severity == "warn"
    assert mono[0] not in failures(findings)
    noisy = trace(call([("iron", 1.0)], t=0.60, se=0.01), call([("iron", 2.0)], t=0.62, se=0.01))
    assert "V-MONOTONE" not in checks(SWEEP, [[1, 0.6]], noisy)


def test_v_trace() -> None:
    tr = trace(call([("iron", 4.0)], energy=2.0, n=5000, t=0.31, r=0.05))
    assert "V-TRACE" in checks(SINGLE, 0.05, tr)  # submitted the reflected share
    assert "V-TRACE" in checks(SINGLE, 0.3, tr)  # rounded or made up
    assert "V-TRACE" in checks(SINGLE, 0.31, trace())  # nothing was simulated
    pct = "What percentage of 2 MeV photons get through 4 cm of iron? Use 5000 photons."
    assert "V-TRACE" not in checks(pct, 31.0, tr)
    two = trace(call([("iron", 4.0)], 2.0, 5000, t=0.31), call([("iron", 4.0)], 2.0, 5000, seed=2))
    assert "V-TRACE" not in checks(SINGLE, 0.3, two)  # several configurations: not checked
    cut = trace(call([("iron", 4.0)], 2.0, 5000, t=0.31), truncated=True)
    assert "V-TRACE" not in checks(SINGLE, 0.3, cut)


def test_without_trace_only_trace_free_checks_run() -> None:
    """Covers R-VER-1: with no trace (e.g. v1 results), trace checks are skipped."""
    assert checks(SINGLE, 0.31, None) == []
    assert verify(extract(SINGLE), None, None) == []


def test_feedback_lists_only_failures() -> None:
    findings = [Finding("V-COUNT", "fail", "use 5000"), Finding("V-MONOTONE", "warn", "odd")]
    text = feedback(findings)
    assert "[V-COUNT] use 5000" in text
    assert "V-MONOTONE" not in text
    assert findings[0].to_dict() == {"check": "V-COUNT", "severity": "fail", "message": "use 5000"}


@pytest.mark.parametrize(
    "check_id",
    ["V-RANGE", "V-ENERGY", "V-LENGTH", "V-COUNT", "V-MATERIAL", "V-UNKNOWN", "V-SWEEP", "V-TRACE"],
)
def test_every_failing_check_has_a_message_for_the_model(check_id: str) -> None:
    """Covers R-VER-1: messages say what to do, not just what is wrong."""
    cases = {
        "V-RANGE": (SINGLE, 31.0, None),
        "V-ENERGY": (SINGLE, 0.31, trace(call([("iron", 4.0)], 1.0, 5000, t=0.31))),
        "V-LENGTH": (SINGLE, 0.31, trace(call([("iron", 5.0)], 2.0, 5000, t=0.31))),
        "V-COUNT": (SINGLE, 0.31, trace(call([("iron", 4.0)], 2.0, 10, t=0.31))),
        "V-MATERIAL": (SINGLE, 0.31, trace(call([("lead", 4.0)], 2.0, 5000, t=0.31))),
        "V-UNKNOWN": ("2 cm of osmium at 1 MeV", 0.3, None),
        "V-SWEEP": (SWEEP, [[1, 0.1]], trace(call([("iron", 10.0)]))),
        "V-TRACE": (SINGLE, 0.3, trace(call([("iron", 4.0)], 2.0, 5000, t=0.31))),
    }
    request, answer, tr = cases[check_id]
    findings = [f for f in verify(extract(request), {"answer": answer}, tr) if f.check == check_id]
    assert findings, check_id
    assert all(f.severity == "fail" and len(f.message) > 40 for f in findings)

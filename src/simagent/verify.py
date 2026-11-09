"""Deterministic verification of a submitted answer against the request and the trace (R-VER).

``verify(facts, result, trace)`` is a pure function: ``facts`` are what the request states
(``request_facts.extract``), ``result`` is the submitted ``{"answer", "data"}``, and ``trace`` is
photonsim's own record of what ran (R-TRACE-1), or ``None`` when no trace exists (then only the
checks that do not need one run). Every check is general (units, physics, consistency with the
request and the trace), never specific to a task. Each finding has a check ID, a severity
(``fail`` triggers a repair, ``warn`` is only reported) and a message written for the model.

Checks (R-VER-2):

* ``V-RANGE``   simulated fractions lie in [0, 1] ([0, 100] when percent is requested).
* ``V-ENERGY``  every simulated energy was stated in the request (after unit conversion).
* ``V-LENGTH``  every stated single thickness was simulated; every simulated thickness was
                stated (single, list, or inside a stated range).
* ``V-COUNT``   every simulated photon count was stated, when the request states one.
* ``V-MATERIAL`` every named material was simulated; no unnamed material was simulated.
* ``V-UNKNOWN`` an unknown material or an energy outside the data range, answered with a number
                instead of ``submit(None, error=...)``.
* ``V-SWEEP``   a stated sweep (a list of >= 3 values, or a range with a step) has >= 3 distinct
                simulated values, and was not stacked into one slab of the summed thickness.
* ``V-MONOTONE`` (warn) transmission does not rise with thickness for one material (4 SE).
* ``V-TRACE``   a scalar fraction from a single simulated configuration equals the traced value.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

import photonsim
from simagent.request_facts import Range, RequestFacts

FATES = ("transmitted", "reflected", "absorbed")
REL_TOL = 1e-6  # stated vs simulated parameters (R-VER-2)
ANSWER_TOL = 1e-9  # answer vs traced value (R-VER-2, V-TRACE)
MONOTONE_SIGMA = 4.0
SWEEP_MIN_POINTS = 3


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str  # "fail" | "warn"
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _close(a: float, b: float, rel: float = REL_TOL) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


def _fmt(values: Any) -> str:
    return ", ".join(f"{v:g}" for v in values)


def _calls(trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not trace or not isinstance(trace.get("calls"), list):
        return []
    return [c for c in trace["calls"] if isinstance(c, dict)]


def _is_number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _numbers(obj: Any) -> Iterator[float]:
    if _is_number(obj):
        yield float(obj)
    elif isinstance(obj, list | tuple):
        for item in obj:
            yield from _numbers(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            yield from _numbers(item)


def _thicknesses(calls: list[dict[str, Any]]) -> list[float]:
    return [float(layer[1]) for c in calls for layer in c.get("layers", [])]


def _in_stated(value: float, singles: tuple[float, ...], ranges: tuple[Range, ...]) -> bool:
    return any(_close(value, s) for s in singles) or any(r.contains(value) for r in ranges)


def _fraction_answer(facts: RequestFacts) -> bool:
    """The answer itself is a simulated fraction (not a thickness, energy or derived value)."""
    return facts.quantity in FATES and not facts.derived


# --------------------------------------------------------------------------------- checks


def check_range(facts: RequestFacts, answer: Any) -> list[Finding]:
    """V-RANGE: a fraction answer (scalar, or the y of [x, y] pairs) lies in [0, 1] or [0, 100]."""
    if not _fraction_answer(facts):
        return []
    high = 100.0 if facts.percent else 1.0
    if _is_number(answer):
        values = [float(answer)]
    elif isinstance(answer, list) and all(
        isinstance(p, list | tuple) and len(p) == 2 and _is_number(p[1]) for p in answer
    ):
        values = [float(p[1]) for p in answer]
    else:
        return []
    bad = [v for v in values if not (math.isfinite(v) and -1e-12 <= v <= high + 1e-12)]
    if not bad:
        return []
    unit = "a percentage between 0 and 100" if facts.percent else "a fraction between 0 and 1"
    return [
        Finding(
            "V-RANGE",
            "fail",
            f"The answer contains {_fmt(bad)}, but a {facts.quantity} share must be {unit}. "
            "Check the arithmetic and submit the simulated value.",
        )
    ]


def check_energy(facts: RequestFacts, calls: list[dict[str, Any]]) -> list[Finding]:
    """V-ENERGY: every simulated energy equals a stated energy or lies in a stated range."""
    stated = facts.all_energies
    if not calls or not (stated or facts.energy_ranges):
        return []
    traced = sorted({float(c["energy_mev"]) for c in calls})
    bad = [e for e in traced if not _in_stated(e, stated, facts.energy_ranges)]
    if not bad:
        return []
    wanted = _fmt(stated) + (" MeV" if stated else "")
    if facts.energy_ranges:
        wanted += (", " if stated else "") + ", ".join(
            f"{r.low:g} to {r.high:g} MeV" for r in facts.energy_ranges
        )
    return [
        Finding(
            "V-ENERGY",
            "fail",
            f"The script simulated {_fmt(bad)} MeV, but the request asks for {wanted} "
            "(converted to MeV). Use exactly the requested energies.",
        )
    ]


def check_length(facts: RequestFacts, calls: list[dict[str, Any]]) -> list[Finding]:
    """V-LENGTH: stated single thicknesses were simulated; simulated thicknesses were stated."""
    if not calls or not (facts.all_lengths or facts.length_ranges):
        return []
    traced = _thicknesses(calls)
    findings = []
    missing = [s for s in facts.lengths_cm if not any(_close(s, t) for t in traced)]
    if missing:
        findings.append(
            Finding(
                "V-LENGTH",
                "fail",
                f"The request states a thickness of {_fmt(missing)} cm (converted to cm), but no "
                "simulated layer has that thickness. Build the slab with the stated thickness.",
            )
        )
    extra = sorted({t for t in traced if not _in_stated(t, facts.all_lengths, facts.length_ranges)})
    if extra:
        findings.append(
            Finding(
                "V-LENGTH",
                "fail",
                f"The script simulated layer thicknesses of {_fmt(extra)} cm, which the request "
                "does not state. Use the stated thicknesses (converted to cm), one per layer.",
            )
        )
    return findings


def check_count(facts: RequestFacts, calls: list[dict[str, Any]]) -> list[Finding]:
    """V-COUNT: every simulated photon count is one the request states."""
    if not calls or not facts.photon_counts:
        return []
    bad = sorted({int(c["n_photons"]) for c in calls} - set(facts.photon_counts))
    if not bad:
        return []
    return [
        Finding(
            "V-COUNT",
            "fail",
            f"The script simulated {', '.join(str(n) for n in bad)} photons, but the request asks "
            f"for {', '.join(str(n) for n in facts.photon_counts)}. Use the stated photon count.",
        )
    ]


def check_material(facts: RequestFacts, calls: list[dict[str, Any]]) -> list[Finding]:
    """V-MATERIAL: named materials were simulated; nothing unnamed was simulated."""
    if not calls or not facts.materials:
        return []
    traced = {str(layer[0]) for c in calls for layer in c.get("layers", [])}
    findings = []
    missing = [m for m in facts.materials if m not in traced]
    if missing:
        findings.append(
            Finding(
                "V-MATERIAL",
                "fail",
                f"The request names {', '.join(missing)}, but no simulated layer uses it.",
            )
        )
    extra = sorted(traced - set(facts.materials))
    if extra:
        findings.append(
            Finding(
                "V-MATERIAL",
                "fail",
                f"The script simulated {', '.join(extra)}, which the request does not mention. "
                f"Use the requested materials: {', '.join(facts.materials)}.",
            )
        )
    return findings


def _energy_limits(facts: RequestFacts) -> tuple[float, float]:
    names = list(facts.materials) or photonsim.list_materials()
    ranges = [photonsim.energy_range(m) for m in names]
    return max(lo for lo, _ in ranges), min(hi for _, hi in ranges)


def check_unknown(facts: RequestFacts, answer: Any) -> list[Finding]:
    """V-UNKNOWN: an impossible request answered with a value instead of an error report."""
    if answer is None:
        return []
    reasons = []
    if facts.unknown_materials:
        reasons.append(
            f"it names {', '.join(facts.unknown_materials)}, which is not an available material "
            f"(available: {', '.join(photonsim.list_materials())})"
        )
    lo, hi = _energy_limits(facts)
    outside = [e for e in facts.all_energies if not lo - 1e-12 <= e <= hi + 1e-12]
    if outside:
        reasons.append(f"{_fmt(outside)} MeV is outside the data range ({lo:g} to {hi:g} MeV)")
    if not reasons:
        return []
    return [
        Finding(
            "V-UNKNOWN",
            "fail",
            "The request cannot be simulated as asked: "
            + "; ".join(reasons)
            + ". Do not substitute anything: report it with "
            "simagent_io.submit(None, error='<what is wrong>').",
        )
    ]


def _sweeps(facts: RequestFacts) -> Iterator[tuple[str, list[float]]]:
    """(dimension, stated values) for every stated sweep: lists of >= 3, ranges with a step."""
    for dim, lists, ranges in (
        ("length", facts.length_lists, facts.length_ranges),
        ("energy", facts.energy_lists, facts.energy_ranges),
    ):
        for values in lists:
            if len(set(values)) >= SWEEP_MIN_POINTS:
                yield dim, list(values)
        for r in ranges:
            if r.step:
                n = math.floor((r.high - r.low) / r.step + 1e-9) + 1
                if n >= SWEEP_MIN_POINTS:
                    yield dim, [r.low + i * r.step for i in range(n)]


def check_sweep(facts: RequestFacts, calls: list[dict[str, Any]]) -> list[Finding]:
    """V-SWEEP: a stated sweep is actually swept, not collapsed or stacked into one slab."""
    if not calls:
        return []
    searching = facts.quantity in ("thickness", "energy")  # a search may stop early
    findings = []
    for dim, values in _sweeps(facts):
        if dim == "length":
            stacked = [
                c
                for c in calls
                if len(c.get("layers", [])) >= 2
                and _close(sum(float(layer[1]) for layer in c["layers"]), sum(values))
            ]
            if stacked:
                findings.append(
                    Finding(
                        "V-SWEEP",
                        "fail",
                        f"The thicknesses {_fmt(values[:8])} cm were stacked into one slab of "
                        f"{sum(values):g} cm. A sweep needs one simulation per thickness, "
                        "e.g. ps.sweep(lambda t: ps.Slab([ps.Layer(material, t)]), values, ...).",
                    )
                )
                continue
            distinct = {round(t, 9) for t in _thicknesses(calls)}
        else:
            distinct = {round(float(c["energy_mev"]), 9) for c in calls}
        if not searching and len(distinct) < SWEEP_MIN_POINTS:
            unit = "cm" if dim == "length" else "MeV"
            findings.append(
                Finding(
                    "V-SWEEP",
                    "fail",
                    f"The request asks for a sweep over {len(values)} values ({_fmt(values[:8])} "
                    f"{unit}), but only {len(distinct)} distinct value(s) were simulated. "
                    "Simulate every requested value.",
                )
            )
    return findings


def check_monotone(calls: list[dict[str, Any]]) -> list[Finding]:
    """V-MONOTONE (warn): single-material transmission must not rise with thickness."""
    groups: dict[tuple[str, float], list[tuple[float, float, float]]] = {}
    for c in calls:
        layers = c.get("layers", [])
        if len(layers) != 1:
            continue
        key = (str(layers[0][0]), float(c["energy_mev"]))
        groups.setdefault(key, []).append(
            (float(layers[0][1]), float(c["transmitted"]), float(c["stderr_transmitted"]))
        )
    findings = []
    for (material, energy), points in groups.items():
        points.sort()
        for (x1, t1, s1), (x2, t2, s2) in itertools.pairwise(points):
            if x2 > x1 and t2 > t1 + MONOTONE_SIGMA * math.hypot(s1, s2):
                findings.append(
                    Finding(
                        "V-MONOTONE",
                        "warn",
                        f"Transmission through {material} at {energy:g} MeV rises from {t1:.4g} "
                        f"({x1:g} cm) to {t2:.4g} ({x2:g} cm), beyond statistical noise.",
                    )
                )
                break
    return findings


def check_trace(
    facts: RequestFacts, answer: Any, calls: list[dict[str, Any]], truncated: bool
) -> list[Finding]:
    """V-TRACE: a scalar fraction from one simulated configuration is the traced value."""
    quantity = facts.quantity
    if quantity is None or not _fraction_answer(facts) or not _is_number(answer) or truncated:
        return []
    value = float(answer)
    if not calls:
        return [
            Finding(
                "V-TRACE",
                "fail",
                f"The answer {value:g} was not computed by photonsim: no simulation ran. "
                "Simulate the requested configuration and submit its result.",
            )
        ]
    configs = {
        (repr(c.get("layers")), c.get("energy_mev"), c.get("n_photons"), c.get("seed"))
        for c in calls
    }
    if len(configs) != 1:
        return []
    traced = float(calls[-1][quantity])
    candidates = [traced * 100.0] if facts.percent else [traced]
    if any(
        math.isclose(value, c, rel_tol=0, abs_tol=ANSWER_TOL * max(1.0, abs(c))) for c in candidates
    ):
        return []
    shown = f"{candidates[0]:.6g}" + (" %" if facts.percent else "")
    return [
        Finding(
            "V-TRACE",
            "fail",
            f"The answer {value:.6g} does not match what the simulation returned "
            f"({quantity} = {shown}). Submit the simulated value directly.",
        )
    ]


def verify(
    facts: RequestFacts, result: dict[str, Any] | None, trace: dict[str, Any] | None
) -> list[Finding]:
    """All findings for one submitted result (R-VER-1). Trace checks need ``trace``."""
    if result is None:
        return []
    answer = result.get("answer")
    findings = check_range(facts, answer) + check_unknown(facts, answer)
    if trace is None:
        return findings
    calls = _calls(trace)
    findings += check_energy(facts, calls)
    findings += check_length(facts, calls)
    findings += check_count(facts, calls)
    findings += check_material(facts, calls)
    findings += check_sweep(facts, calls)
    findings += check_trace(facts, answer, calls, bool(trace.get("truncated")))
    findings += check_monotone(calls)
    return findings


def failures(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "fail"]


def feedback(findings: list[Finding]) -> str:
    """Repair feedback for the model, in the same style as other errors (R-VER-4)."""
    lines = ["The script ran, but its answer failed verification against the request:"]
    lines += [f"- [{f.check}] {f.message}" for f in failures(findings)]
    return "\n".join(lines)

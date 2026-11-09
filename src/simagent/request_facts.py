"""Facts stated in a request, extracted deterministically (R-REQ-1..3). No LLM.

What is extracted, converted to simulator units (cm, MeV):

* energies (eV, keV, MeV, GeV) and lengths (um, mm, cm, m, inches): single values, lists
  ("0.5, 1 and 2 cm": one unit for all), and ranges ("from A to B", "between A and B",
  "A to B") with a step when stated ("in 0.5 cm steps", "steps of 2 cm", "every 5 cm",
  "whole centimetres");
* photon counts ("20000 photons", "1e5 photons", "100,000 photons") and seeds ("seed 3");
* the requested quantity (transmitted / reflected / absorbed / thickness / energy), whether
  the answer is requested in percent, and whether it is *derived* from simulated values (a
  ratio, factor, difference, change, fit or slope) rather than a simulated fraction itself;
* known materials (with aliases such as "aluminum") and unknown material candidates in material
  position ("5 cm of X", "a 3 cm X plate", "an X plate 4 cm thick").

**Silent when unsure (R-REQ-3):** a phrase that does not match cleanly produces no fact. A missing
fact only disables a verification check; a wrong fact would cause false alarms. For example "in"
is never read as inches, a comma that is not a thousands separator gives no number, a candidate
that contains a known material name is not reported as unknown, and when several fates are
mentioned the requested quantity is left unknown.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import photonsim

ENERGY_UNITS = {"ev": 1e-6, "kev": 1e-3, "mev": 1.0, "gev": 1e3}
LENGTH_UNITS = {
    "um": 1e-4,
    "µm": 1e-4,
    "micrometre": 1e-4,
    "micrometres": 1e-4,
    "micrometer": 1e-4,
    "micrometers": 1e-4,
    "micron": 1e-4,
    "microns": 1e-4,
    "mm": 0.1,
    "millimetre": 0.1,
    "millimetres": 0.1,
    "millimeter": 0.1,
    "millimeters": 0.1,
    "cm": 1.0,
    "centimetre": 1.0,
    "centimetres": 1.0,
    "centimeter": 1.0,
    "centimeters": 1.0,
    "m": 100.0,
    "metre": 100.0,
    "metres": 100.0,
    "meter": 100.0,
    "meters": 100.0,
    "inch": 2.54,
    "inches": 2.54,
}
MATERIAL_ALIASES = {
    **{name: name for name in photonsim.list_materials()},
    "aluminum": "aluminium",
    "polythene": "polyethylene",
}

_NUM = r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w,]\d)"
_EUNIT = r"(?:GeV|MeV|keV|eV)(?![A-Za-z])"
_LUNIT = (
    r"(?:µm|um|micromet(?:re|er)s?|microns?|mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?"
    r"|met(?:re|er)s?|m|inch(?:es)?)(?![A-Za-z])"
)
_UNIT = rf"(?:{_EUNIT}|{_LUNIT})"
_STEP_PATTERNS = [
    rf"\bin\s+(?:steps\s+of\s+)?(?P<n>{_NUM})\s*-?\s*(?P<u>{_UNIT})\s+(?:steps?|increments?)\b",
    rf"\b(?:steps?|increments?)\s+of\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})",
    rf"\bgrid\s+of\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})\s+steps?\b",
    rf"\bevery\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})",
]
_WHOLE_CM = re.compile(r"\b(?:whole|integer)\s+centimet(?:re|er)s?\b|\bin\s+1\s*cm\s+steps\b", re.I)
_RANGE_PATTERNS = [
    rf"\bfrom\s+(?P<a>{_NUM})\s*(?P<ua>{_UNIT})?\s*(?:up\s+)?to\s+(?P<b>{_NUM})\s*(?P<ub>{_UNIT})",
    rf"\bbetween\s+(?P<a>{_NUM})\s*(?P<ua>{_UNIT})?\s+and\s+(?P<b>{_NUM})\s*(?P<ub>{_UNIT})",
    # "A to B", and "A-B" written with an en dash (a named regex escape below)
    rf"(?P<a>{_NUM})\s*(?P<ua>{_UNIT})?\s*(?:to|\N{{EN DASH}})\s*(?P<b>{_NUM})\s*(?P<ub>{_UNIT})",
]
_LIST = re.compile(
    rf"(?P<items>(?:{_NUM}\s*(?:,\s*|,?\s+(?:and|or)\s+))+{_NUM})\s*(?P<u>{_UNIT})", re.I
)
_SINGLE = re.compile(rf"(?P<n>{_NUM})\s*-?\s*(?P<u>{_UNIT})", re.I)
_COUNT = re.compile(
    rf"(?<!\bin\s)(?P<n>{_NUM}|10\s*\^\s*\d+)\s+(?:photons|histories|particles|gammas)\b", re.I
)
_SEED = re.compile(r"\bseeds?\s*(?:=|:|of|number)?\s*(?P<n>\d+)\b", re.I)
_PERCENT = re.compile(
    r"\bpercentage\b|\bin\s+percent\b|\bas\s+a\s+percent(?:age)?\b|\bper\s*cent\s+of\s+the\b",
    re.I,
)
_FATES = {
    "transmitted": re.compile(
        r"\btransmi(?:tted|ssion|ts?)\b|\b(?:gets?|get|pass(?:es)?|makes? it|lets?)\s+through\b",
        re.I,
    ),
    "reflected": re.compile(r"\breflect\w*|\bback-?\s?scatter\w*|\bbounces?\s+back\b", re.I),
    "absorbed": re.compile(r"\babsorb\w*|\babsorption\b", re.I),
}
_DERIVED = re.compile(
    r"\b(?:ratio|factor|difference|minus|slope|fit|coefficient|increase|decrease|drop|change)"
    r"s?\b|\bhow\s+much\s+(?:larger|smaller|more|less|higher|lower)\b",
    re.I,
)
_SEARCH = {
    "thickness": re.compile(
        r"\bhow\s+(?:thick|deep)\b|\b(?:smallest|thinnest|minimum|minimal)\b[^.?!]*?"
        r"\b(?:thickness|depth|layer|slab|plate|shield|block|wall|sheet)\b"
        r"|\bthickness\s+at\s+which\b",
        re.I,
    ),
    "energy": re.compile(
        r"\b(?:lowest|highest|minimum|maximum|smallest|largest)\s+(?:photon\s+)?energy\b"
        r"|\b(?:what|which)\s+(?:photon\s+)?energy\b|\babove\s+what\s+(?:photon\s+)?energy\b",
        re.I,
    ),
}
_CONTAINER = r"(?:walls?|slabs?|shields?|layers?|plates?|blocks?|sheets?|panels?|barriers?|tanks?)"
_CAND = r"(?P<cand>[A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*)?)"
_UNKNOWN_PATTERNS = [
    re.compile(rf"{_NUM}\s*-?\s*{_LUNIT}\s+of\s+{_CAND}", re.I),
    re.compile(rf"{_NUM}\s*-?\s*{_LUNIT}(?:\s+thick)?\s+{_CAND}\s+{_CONTAINER}\b", re.I),
    re.compile(
        rf"\b{_CAND}\s+{_CONTAINER}\s+(?:that\s+is\s+|of\s+)?{_NUM}\s*-?\s*{_LUNIT}\s+thick\b",
        re.I,
    ),
]
_NOT_MATERIAL = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "each",
        "it",
        "them",
        "this",
        "that",
        "these",
        "those",
        "material",
        "materials",
        "same",
        "its",
        "their",
        "my",
        "your",
        "our",
        "at",
        "with",
        "for",
        "and",
        "or",
        "to",
        "in",
        "on",
        "by",
        "from",
        "per",
        "then",
        "followed",
        "facing",
        "behind",
        "thick",
        "thin",
        "total",
        "solid",
        "plain",
        "pure",
        "one",
        "two",
        "three",
        "four",
        "layer",
        "layers",
        "slab",
        "slabs",
        "wall",
        "walls",
        "shield",
        "shields",
        "plate",
        "plates",
        "block",
        "blocks",
        "sheet",
        "sheets",
        "tank",
        "tanks",
        "panel",
        "panels",
        "barrier",
        "barriers",
        "photon",
        "photons",
        "beam",
        "beams",
        "gamma",
        "gammas",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "how",
        "when",
        "if",
        "than",
        "more",
        "less",
        "about",
        "roughly",
        "some",
        "any",
        "every",
        "all",
        "both",
        "either",
        "neither",
        "depth",
        "thickness",
        "alone",
        "only",
    ]
)


@dataclass(frozen=True)
class Range:
    """A stated range in simulator units; ``step`` when the request states one."""

    low: float
    high: float
    step: float | None = None

    def contains(self, value: float, rel: float = 1e-6) -> bool:
        tol = rel * max(abs(self.low), abs(self.high), 1.0)
        return self.low - tol <= value <= self.high + tol


@dataclass(frozen=True)
class RequestFacts:
    """Facts stated in the request; every field may be empty (nothing stated or unclear)."""

    energies_mev: tuple[float, ...] = ()
    lengths_cm: tuple[float, ...] = ()
    energy_lists: tuple[tuple[float, ...], ...] = ()
    length_lists: tuple[tuple[float, ...], ...] = ()
    energy_ranges: tuple[Range, ...] = ()
    length_ranges: tuple[Range, ...] = ()
    photon_counts: tuple[int, ...] = ()
    seeds: tuple[int, ...] = ()
    quantity: str | None = None
    percent: bool = False
    derived: bool = False
    materials: tuple[str, ...] = ()
    unknown_materials: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def all_energies(self) -> tuple[float, ...]:
        return self.energies_mev + tuple(v for lst in self.energy_lists for v in lst)

    @property
    def all_lengths(self) -> tuple[float, ...]:
        return self.lengths_cm + tuple(v for lst in self.length_lists for v in lst)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequestFacts:
        """Inverse of ``to_dict`` (the agent state stores facts as plain data)."""
        ranges = {"energy_ranges", "length_ranges"}
        nested = {"energy_lists", "length_lists"}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key in ranges:
                kwargs[key] = tuple(Range(**r) for r in value)
            elif key in nested:
                kwargs[key] = tuple(tuple(v) for v in value)
            elif isinstance(value, list | tuple):
                kwargs[key] = tuple(value)
            else:
                kwargs[key] = value
        return cls(**kwargs)


def parse_number(text: str) -> float | None:
    """``"100,000"`` -> 100000, ``"1e5"`` -> 100000, ``"10^5"`` -> 100000; None if unclear."""
    s = text.strip().replace(" ", "")
    if m := re.fullmatch(r"10\^(\d+)", s):
        return float(10 ** int(m.group(1)))
    if "," in s:
        if not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
            return None
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _unit(text: str) -> tuple[str, float] | None:
    """(dimension, factor to simulator units) for a unit string, or None."""
    u = text.strip()
    if u.lower() in ENERGY_UNITS:
        # "meV" is milli-electronvolt, not MeV: too ambiguous to read either way.
        return None if u == "meV" else ("energy", ENERGY_UNITS[u.lower()])
    if u.lower() in LENGTH_UNITS:
        # "M" (as in "1 M photons") is not metres.
        return None if u.lower() == "m" and u != "m" else ("length", LENGTH_UNITS[u.lower()])
    return None


def _round(value: float) -> float:
    return float(f"{value:.12g}")  # 25 mm -> 2.5, not 2.5000000000000004


class _Text:
    """The request with already-used spans blanked out, so each phrase is read once."""

    def __init__(self, text: str) -> None:
        self.original = text
        self.masked = text

    def mask(self, start: int, end: int) -> None:
        self.masked = self.masked[:start] + " " * (end - start) + self.masked[end:]


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.?!])\s+", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _steps(t: _Text) -> list[tuple[int, str, float]]:
    """(position, dimension, step) for every stated step; the step text is masked."""
    out: list[tuple[int, str, float]] = []
    for pattern in _STEP_PATTERNS:
        for m in re.finditer(pattern, t.masked, re.I):
            n, unit = parse_number(m.group("n")), _unit(m.group("u"))
            if n is not None and unit is not None and n > 0:
                out.append((m.start(), unit[0], _round(n * unit[1])))
                t.mask(m.start(), m.end())
    for m in _WHOLE_CM.finditer(t.masked):
        out.append((m.start(), "length", 1.0))
        t.mask(m.start(), m.end())
    return out


def _ranges(t: _Text, steps: list[tuple[int, str, float]]) -> dict[str, list[Range]]:
    found: dict[str, list[Range]] = {"energy": [], "length": []}
    sentences = _sentences(t.original)
    for pattern in _RANGE_PATTERNS:
        for m in re.finditer(pattern, t.masked, re.I):
            a, b = parse_number(m.group("a")), parse_number(m.group("b"))
            ub = _unit(m.group("ub"))
            ua = _unit(m.group("ua")) if m.group("ua") else ub
            if a is None or b is None or ub is None or ua is None or ua[0] != ub[0]:
                continue
            low, high = sorted((_round(a * ua[1]), _round(b * ub[1])))
            dim = ub[0]
            sentence = next((s for s in sentences if s[0] <= m.start() < s[1] + 1), None)
            step = next(
                (
                    st
                    for pos, d, st in steps
                    if d == dim and sentence is not None and sentence[0] <= pos <= sentence[1]
                ),
                None,
            )
            found[dim].append(Range(low, high, step))
            t.mask(m.start(), m.end())
    return found


def _lists(t: _Text) -> dict[str, list[tuple[float, ...]]]:
    found: dict[str, list[tuple[float, ...]]] = {"energy": [], "length": []}
    for m in _LIST.finditer(t.masked):
        unit = _unit(m.group("u"))
        values = [parse_number(x) for x in re.findall(_NUM, m.group("items"))]
        if unit is None or any(v is None for v in values) or len(values) < 2:
            continue
        found[unit[0]].append(tuple(_round(v * unit[1]) for v in values if v is not None))
        t.mask(m.start(), m.end())
    return found


def _singles(t: _Text) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {"energy": [], "length": []}
    for m in _SINGLE.finditer(t.masked):
        n, unit = parse_number(m.group("n")), _unit(m.group("u"))
        if n is None or unit is None:
            continue
        value = _round(n * unit[1])
        if value not in found[unit[0]]:
            found[unit[0]].append(value)
    return found


def _counts(text: str) -> tuple[int, ...]:
    counts: list[int] = []
    for m in _COUNT.finditer(text):
        n = parse_number(m.group("n"))
        if n is not None and n >= 1 and n.is_integer() and int(n) not in counts:
            counts.append(int(n))
    return tuple(counts)


def _materials(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for m in re.finditer(r"[A-Za-z]+", text):
        word = m.group(0).lower()
        if word == "lead" and re.match(r"\s+to\b", text[m.end() :]):
            continue  # "lead to" is the verb
        canonical = MATERIAL_ALIASES.get(word)
        if canonical and canonical not in found:
            found.append(canonical)
    return tuple(found)


def _unknown_materials(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in _UNKNOWN_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group("cand").lower().split()
            while raw and raw[0] in _NOT_MATERIAL:  # "an iron plate": skip the article
                raw.pop(0)
            words: list[str] = []
            for word in raw:
                if word in _NOT_MATERIAL:  # "iron with 100 photons": stop at "with"
                    break
                words.append(word)
            if not words or any(w in MATERIAL_ALIASES for w in words):
                continue
            name = " ".join(words)
            if name not in found:
                found.append(name)
    return tuple(found)


def _quantity(text: str) -> str | None:
    searches = [name for name, rx in _SEARCH.items() if rx.search(text)]
    if len(searches) == 1:
        return searches[0]
    if searches:
        return None
    fates = [name for name, rx in _FATES.items() if rx.search(text)]
    return fates[0] if len(fates) == 1 else None


def extract(request: str) -> RequestFacts:
    """Extract the facts stated in ``request`` (R-REQ-1); silent when unsure (R-REQ-3)."""
    t = _Text(request)
    steps = _steps(t)
    ranges = _ranges(t, steps)
    lists = _lists(t)
    singles = _singles(t)
    return RequestFacts(
        energies_mev=tuple(singles["energy"]),
        lengths_cm=tuple(singles["length"]),
        energy_lists=tuple(lists["energy"]),
        length_lists=tuple(lists["length"]),
        energy_ranges=tuple(ranges["energy"]),
        length_ranges=tuple(ranges["length"]),
        photon_counts=_counts(request),
        seeds=tuple(dict.fromkeys(int(m.group("n")) for m in _SEED.finditer(request))),
        quantity=_quantity(request),
        percent=bool(_PERCENT.search(request)),
        derived=bool(_DERIVED.search(request)),
        materials=_materials(request),
        unknown_materials=_unknown_materials(request),
    )

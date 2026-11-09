"""Deterministic request-fact extraction (R-REQ-1..3).

None of the phrasings below is taken from the dev or held-out task sets (R-REQ-2); a test checks
that each one is far from every task prompt (token-set Jaccard < 0.6, the held-out rule).
"""

import re
from pathlib import Path
from typing import Any

import pytest

from simagent.evaluation.tasks import TASK_SETS, load_task_set
from simagent.request_facts import Range, extract, parse_number

ROOT = Path(__file__).resolve().parents[1]

# (phrasing, expected fields). Only the listed fields are checked; "silent" cases check that a
# fact is *absent* (an empty tuple / None / False).
CASES: list[tuple[str, dict[str, Any]]] = [
    # --- energies and their units
    ("Gammas at 662 keV hit a brick.", {"energies_mev": (0.662,)}),
    ("A 1.17 MeV line from cobalt.", {"energies_mev": (1.17,)}),
    ("Assume 0.002 GeV photons.", {"energies_mev": (2.0,)}),
    ("A 150000 eV x-ray tube spectrum peak.", {"energies_mev": (0.15,)}),
    ("photons of 4MeV", {"energies_mev": (4.0,)}),
    ("a 2 mev source, typed lowercase", {"energies_mev": (2.0,)}),
    ("a 5 meV phonon", {"energies_mev": ()}),  # milli-eV is ambiguous: silent
    # --- lengths and their units
    ("Behind 35 mm of steel-free aluminum.", {"lengths_cm": (3.5,), "materials": ("aluminium",)}),
    ("A sheet 250 um thick.", {"lengths_cm": (0.025,)}),
    ("A 2 m deep pool of water.", {"lengths_cm": (200.0,), "materials": ("water",)}),
    ("Use a 3-inch block.", {"lengths_cm": (7.62,)}),
    ("half an inch", {"lengths_cm": ()}),  # no number: silent
    ("a 0.75 inches pane", {"lengths_cm": (1.905,)}),
    ("12 centimetres of polythene", {"lengths_cm": (12.0,), "materials": ("polyethylene",)}),
    ("one in 1000 gammas escape", {"photon_counts": ()}),  # "1 in 1000" is not a count
    ("1 in 10 cm", {"lengths_cm": (10.0,)}),  # "in" is never inches
    ("Give it 1 M photons.", {"lengths_cm": (), "photon_counts": ()}),  # "M" is not metres
    # --- lists
    ("Try 2, 4 and 8 cm of lead.", {"length_lists": ((2.0, 4.0, 8.0),), "lengths_cm": ()}),
    ("at 0.3, 0.6, 0.9 MeV", {"energy_lists": ((0.3, 0.6, 0.9),), "energies_mev": ()}),
    ("walls of 15 or 25 cm", {"length_lists": ((15.0, 25.0),)}),
    ("plates of 5, 10, 20 mm", {"length_lists": ((0.5, 1.0, 2.0),)}),
    # --- ranges and steps
    (
        "Vary the concrete from 10 to 50 cm in 5 cm steps.",
        {"length_ranges": (Range(10.0, 50.0, 5.0),), "lengths_cm": ()},
    ),
    (
        "Thickness between 0.5 and 4 cm, steps of 0.25 cm.",
        {"length_ranges": (Range(0.5, 4.0, 0.25),)},
    ),
    ("energies 0.2 to 2 MeV", {"energy_ranges": (Range(0.2, 2.0, None),), "energies_mev": ()}),
    ("from 300 keV up to 3 MeV", {"energy_ranges": (Range(0.3, 3.0, None),)}),
    ("every 2 cm from 2 cm to 20 cm", {"length_ranges": (Range(2.0, 20.0, 2.0),)}),
    ("scan whole centimetres from 5 to 40 cm", {"length_ranges": (Range(5.0, 40.0, 1.0),)}),
    ("depths of 3\N{EN DASH}9 cm", {"length_ranges": (Range(3.0, 9.0, None),)}),
    (
        "between 1 and 3 MeV, then in 2 cm steps from 2 to 12 cm",
        {"energy_ranges": (Range(1.0, 3.0, None),), "length_ranges": (Range(2.0, 12.0, 2.0),)},
    ),
    # --- photon counts and seeds
    ("Run 250000 photons.", {"photon_counts": (250000,)}),
    ("Run 250,000 photons.", {"photon_counts": (250000,)}),
    ("with 2e4 histories per point", {"photon_counts": (20000,)}),
    ("use 10^6 photons", {"photon_counts": (1000000,)}),
    ("Run 2,50 photons.", {"photon_counts": ()}),  # not a thousands separator: silent
    ("seed=42, then seed 7", {"seeds": (42, 7)}),
    # --- requested quantity and percent
    ("How much of the beam leaks through?", {"quantity": None}),  # unclear: silent
    ("What share gets through 6 cm of iron?", {"quantity": "transmitted"}),
    ("How much back-scatter from the floor?", {"quantity": "reflected"}),
    ("Fraction deposited (absorbed) in the slab?", {"quantity": "absorbed"}),
    ("Is more transmitted or absorbed?", {"quantity": None}),  # two fates: silent
    ("How thick a wall do I need?", {"quantity": "thickness"}),
    ("the thinnest sheet that stops 90 % of them", {"quantity": "thickness"}),
    ("at least 5000 photons per point, transmitted fraction", {"quantity": "transmitted"}),
    ("Which energy penetrates best?", {"quantity": "energy"}),
    ("Give the answer as a percentage.", {"percent": True}),
    ("Report T(4 MeV) / T(1 MeV) as a ratio.", {"derived": True}),
    ("By how much lower is the reflected share?", {"derived": True}),
    ("Fit a straight line and give the slope.", {"derived": True}),
    ("Report the transmitted share for 9 cm.", {"derived": False}),
    ("below 5 % transmission", {"percent": False}),  # a threshold, not a percent answer
    # --- materials
    ("aluminum and aluminium are the same", {"materials": ("aluminium",)}),
    ("Lead, then IRON, then water.", {"materials": ("lead", "iron", "water")}),
    ("this will lead to errors", {"materials": ()}),  # the verb
    ("8 cm of depleted uranium", {"unknown_materials": ("depleted uranium",)}),
    ("a 2 cm copper sheet", {"unknown_materials": ("copper",)}),
    ("a bismuth slab 3 cm thick", {"unknown_materials": ("bismuth",)}),
    ("4 cm of borated polyethylene", {"unknown_materials": (), "materials": ("polyethylene",)}),
    ("6 cm of each material", {"unknown_materials": ()}),
    ("a 10 cm thick wall", {"unknown_materials": ()}),
    ("2 cm of the plate", {"unknown_materials": ()}),
]


@pytest.mark.parametrize(("phrase", "expected"), CASES)
def test_extract(phrase: str, expected: dict[str, Any]) -> None:
    """Covers R-REQ-1 and R-REQ-3 (silent cases expect empty fields)."""
    facts = extract(phrase)
    got = {key: getattr(facts, key) for key in expected}
    assert got == expected, phrase


def test_at_least_forty_phrasings() -> None:
    """Covers R-REQ-2."""
    assert len(CASES) >= 40


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))


def test_phrasings_are_not_taken_from_the_task_sets() -> None:
    """Covers R-REQ-2: every phrasing is far from every dev and held-out prompt."""
    prompts = [t.prompt for name in TASK_SETS for t in load_task_set(name, ROOT)]
    for phrase, _ in CASES:
        a = _tokens(phrase)
        for prompt in prompts:
            b = _tokens(prompt)
            assert len(a & b) / len(a | b) < 0.6, (phrase, prompt)
            assert phrase.lower() not in prompt.lower(), (phrase, prompt)


def test_combined_request() -> None:
    facts = extract(
        "Using 50,000 photons and seed 3, find the smallest water depth from 1 to 30 cm in "
        "1 cm steps behind 2 cm of lead at which less than 5 % of 1.25 MeV photons pass through."
    )
    assert facts.photon_counts == (50000,)
    assert facts.seeds == (3,)
    assert facts.length_ranges == (Range(1.0, 30.0, 1.0),)
    assert facts.lengths_cm == (2.0,)
    assert facts.energies_mev == (1.25,)
    assert facts.quantity == "thickness"
    assert facts.materials == ("water", "lead")
    assert facts.all_lengths == (2.0,)
    assert facts.to_dict()["length_ranges"] == ({"low": 1.0, "high": 30.0, "step": 1.0},)


def test_all_values_include_lists() -> None:
    facts = extract("3 cm of iron, and 1, 2 and 4 cm of water, at 0.5 MeV and at 1, 2 MeV")
    assert facts.all_lengths == (3.0, 1.0, 2.0, 4.0)
    assert facts.all_energies == (0.5, 1.0, 2.0)


def test_range_contains() -> None:
    r = Range(1.0, 2.0)
    assert r.contains(1.0)
    assert r.contains(2.0 + 1e-9)
    assert not r.contains(2.1)


@pytest.mark.parametrize(
    ("text", "value"),
    [("100,000", 100000.0), ("1e5", 100000.0), ("10^3", 1000.0), ("0.5", 0.5), ("1,2", None)],
)
def test_parse_number(text: str, value: float | None) -> None:
    assert parse_number(text) == value

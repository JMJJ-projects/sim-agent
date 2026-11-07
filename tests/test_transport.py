"""Unit tests for the transport kernel."""

import numpy as np

from photonsim.transport import transport


def _run(mu_t: float, mu_a: float, t: float, n: int = 20_000, seed: int = 0) -> tuple[int, ...]:
    tally = transport(
        np.array([t]), np.array([mu_t]), np.array([mu_a]), n, np.random.default_rng(seed)
    )
    assert tally.total == n
    return tally.transmitted, tally.reflected, tally.absorbed


def test_every_photon_ends_somewhere() -> None:
    """Covers R-SIM-1."""
    tally = transport(
        np.array([1.0, 2.0, 0.5]),
        np.array([0.2, 0.8, 0.5]),
        np.array([0.05, 0.4, 0.1]),
        10_000,
        np.random.default_rng(1),
    )
    assert tally.total == 10_000
    assert min(tally.transmitted, tally.reflected, tally.absorbed) > 0


def test_pure_absorber_never_reflects() -> None:
    """Covers R-SIM-2: with mu_abs == mu_total every interaction absorbs."""
    _, reflected, _ = _run(0.5, 0.5, 2.0)
    assert reflected == 0


def test_pure_scatterer_never_absorbs() -> None:
    """Covers R-SIM-2: mu_abs -> 0 means (almost) no absorption."""
    _, _, absorbed = _run(0.5, 1e-12, 2.0)
    assert absorbed == 0


def test_same_seed_same_tally() -> None:
    """Covers R-SIM-6."""
    assert _run(0.3, 0.1, 3.0, seed=7) == _run(0.3, 0.1, 3.0, seed=7)


def test_zero_photons() -> None:
    assert _run(0.3, 0.1, 3.0, n=0) == (0, 0, 0)

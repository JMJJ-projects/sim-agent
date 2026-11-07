"""The API reference given to the model is current and small."""

from pathlib import Path

from photonsim.apidoc import render

API_MD = Path(__file__).resolve().parents[1] / "docs" / "api.md"


def test_api_doc_is_not_stale() -> None:
    """Covers R-SIM-8: regenerate with `python scripts/gen_api_doc.py` if this fails."""
    assert API_MD.read_text(encoding="utf-8") == render()


def test_api_doc_fits_small_context() -> None:
    """Covers R-SIM-8: at most ~1500 tokens (estimated as characters / 4)."""
    assert len(render()) / 4 <= 1500


def test_api_doc_mentions_every_public_name() -> None:
    text = render()
    for name in ["Layer(", "Slab(", "simulate(", "sweep(", "list_materials(", "energy_range("]:
        assert name in text
    assert "Result" in text

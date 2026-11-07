"""The committed graph diagram matches the code."""

from pathlib import Path

from simagent.graph import mermaid

GRAPH_MMD = Path(__file__).resolve().parents[1] / "docs" / "graph.mmd"


def test_graph_diagram_is_not_stale() -> None:
    """Regenerate with `python scripts/export_graph.py` if this fails."""
    assert GRAPH_MMD.read_text(encoding="utf-8") == mermaid()


def test_graph_has_all_nodes() -> None:
    """Covers R-AG-1."""
    text = mermaid()
    for node in ["generate", "check_policy", "execute", "evaluate_run", "repair", "finalize"]:
        assert node in text

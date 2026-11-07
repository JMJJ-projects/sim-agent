"""Tests for code-block extraction."""

import pytest

from simagent.codeblock import FORMAT_ERROR, extract


def test_single_block_with_explanation() -> None:
    """Covers R-AG-3."""
    reply = "I simulate lead.\n\n```python\nimport photonsim\nprint(1)\n```\nDone."
    ex = extract(reply)
    assert ex.code == "import photonsim\nprint(1)\n"
    assert ex.error is None
    assert ex.refusal is None
    assert ex.explanation == "I simulate lead. Done."


@pytest.mark.parametrize("lang", ["python", "py", "Python3", "python title.py"])
def test_python_labels(lang: str) -> None:
    assert extract(f"```{lang}\nx = 1\n```").code == "x = 1\n"


def test_crlf_and_indented_fences() -> None:
    assert extract("text\r\n  ```python\r\nx = 1\r\n  ```\r\n").code == "x = 1\n"


@pytest.mark.parametrize(
    ("reply", "detail"),
    [
        ("no code here", "found 0"),
        ("```python\na\n```\n```python\nb\n```", "found 2"),
        ("```\nx = 1\n```", "without the `python` label"),
        ("```python\nx = 1\n", "not closed"),
        ("```python\n\n```", "empty"),
    ],
)
def test_format_errors(reply: str, detail: str) -> None:
    """Covers R-AG-3."""
    ex = extract(reply)
    assert ex.code is None
    assert ex.error is not None
    assert ex.error.startswith(FORMAT_ERROR)
    assert detail in ex.error


def test_other_language_blocks_are_ignored() -> None:
    reply = "```bash\npip install x\n```\n```python\nx = 1\n```"
    assert extract(reply).code == "x = 1\n"


def test_refusal_wins_over_code() -> None:
    """Covers R-AG-9."""
    ex = extract("REFUSED: reading files is outside the simulator's scope\n```python\nx=1\n```")
    assert ex.code is None
    assert ex.refusal == "reading files is outside the simulator's scope"


def test_refusal_without_reason() -> None:
    assert extract("\n  refused:\n").refusal


def test_long_explanation_truncated() -> None:
    ex = extract("word " * 1000 + "\n```python\nx = 1\n```")
    assert len(ex.explanation) <= 1200
    assert ex.explanation.endswith("...")

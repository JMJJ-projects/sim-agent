"""Extraction of exactly one fenced Python code block from a model reply (R-AG-3).

The reply format the prompts ask for is: a short explanation paragraph, then exactly one
```` ```python ```` block. A reply whose first non-empty line starts with ``REFUSED:`` is a
refusal (R-AG-9) and never yields code, even if it also contains a block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PYTHON_LANGS = frozenset({"python", "py", "python3"})
FORMAT_ERROR = "reply must contain exactly one ```python block"
REFUSAL_PREFIX = "REFUSED:"
MAX_EXPLANATION_CHARS = 1200

_FENCE = re.compile(r"^\s*```\s*([^\s`]*)")


@dataclass(frozen=True)
class Extraction:
    """Result of ``extract``. Exactly one of ``code``, ``error`` or ``refusal`` is set."""

    code: str | None
    explanation: str
    error: str | None = None
    refusal: str | None = None


def _explanation(lines: list[str]) -> str:
    text = " ".join(" ".join(lines).split())
    if len(text) > MAX_EXPLANATION_CHARS:
        text = text[: MAX_EXPLANATION_CHARS - 3].rstrip() + "..."
    return text


def extract(reply: str) -> Extraction:
    """Split ``reply`` into code, explanation, and a format error or refusal."""
    lines = reply.replace("\r\n", "\n").split("\n")
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    if first.upper().startswith(REFUSAL_PREFIX):
        reason = first[len(REFUSAL_PREFIX) :].strip() or "request is outside the simulator's scope"
        return Extraction(code=None, explanation="", refusal=reason)

    blocks: list[tuple[str, list[str]]] = []
    prose: list[str] = []
    current: list[str] | None = None
    lang = ""
    for line in lines:
        if current is None:
            m = _FENCE.match(line)
            if m:
                lang = m.group(1).lower()
                current = []
            else:
                prose.append(line)
        elif line.strip().startswith("```") and line.strip().strip("`") == "":
            blocks.append((lang, current))
            current = None
        else:
            current.append(line)

    explanation = _explanation(prose)
    python_blocks = [body for lg, body in blocks if lg in PYTHON_LANGS]
    if current is not None:
        detail = "a code block is not closed with ``` (was the reply cut off?)"
        return Extraction(code=None, explanation=explanation, error=f"{FORMAT_ERROR}; {detail}")
    if len(python_blocks) == 1:
        code = "\n".join(python_blocks[0]).strip("\n") + "\n"
        if not code.strip():
            return Extraction(
                code=None, explanation=explanation, error=f"{FORMAT_ERROR}; the block is empty"
            )
        return Extraction(code=code, explanation=explanation)
    if not python_blocks and blocks:
        detail = f"found {len(blocks)} block(s) without the `python` label"
    else:
        detail = f"found {len(python_blocks)}"
    return Extraction(code=None, explanation=explanation, error=f"{FORMAT_ERROR} ({detail})")

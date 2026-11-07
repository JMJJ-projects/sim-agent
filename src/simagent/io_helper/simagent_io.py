"""Result submission helper used by generated code inside the sandbox (R-SBX-7).

Generated scripts call ``simagent_io.submit(answer, **data)`` exactly once. The result is written
as JSON to ``$SIMAGENT_OUT_DIR/result.json`` (``/out/result.json`` in the sandbox).

This module is standalone (standard library only) because it is copied into the sandbox image.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

__all__ = ["MAX_RESULT_BYTES", "submit"]

MAX_RESULT_BYTES = 1_000_000
_submitted = False


def _out_dir() -> Path:
    return Path(os.environ.get("SIMAGENT_OUT_DIR", "/out"))


def _to_jsonable(obj: Any, path: str = "answer") -> Any:
    """Convert numpy values, tuples and objects with ``to_dict()`` into plain JSON types."""
    if obj is None or isinstance(obj, bool | str):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"submit(): {path} is {obj!r}; NaN and infinity are not valid JSON")
        return obj
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError(f"submit(): {path} has a non-string key {k!r}")
            out[k] = _to_jsonable(v, f"{path}[{k!r}]")
        return out
    if isinstance(obj, list | tuple):
        return [_to_jsonable(v, f"{path}[{i}]") for i, v in enumerate(obj)]
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return _to_jsonable(to_dict(), path)
    tolist = getattr(obj, "tolist", None)  # numpy scalars and arrays
    if callable(tolist):
        return _to_jsonable(tolist(), path)
    raise ValueError(
        f"submit(): {path} has type {type(obj).__name__}, which is not JSON-serialisable; "
        "use numbers, strings, booleans, None, lists and dicts"
    )


def submit(answer: Any, **data: Any) -> None:
    """Report the final answer (and optional supporting data). Call exactly once.

    ``answer`` is the direct answer to the request (a number, string, list or dict). Extra
    keyword arguments are stored under ``data``. Values must be JSON-serialisable; numpy values
    and photonsim ``Result`` objects are converted automatically.
    """
    global _submitted
    if _submitted:
        raise RuntimeError("submit() may only be called once per script")
    payload = {"answer": _to_jsonable(answer), "data": _to_jsonable(data, "data")}
    text = json.dumps(payload, allow_nan=False, indent=2)
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError(
            f"submit(): result is larger than {MAX_RESULT_BYTES} bytes; send less data"
        )
    out_dir = _out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "result.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(out_dir / "result.json")
    _submitted = True

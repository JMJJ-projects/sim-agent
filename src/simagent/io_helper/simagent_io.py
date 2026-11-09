"""Result submission helper used by generated code inside the sandbox (R-SBX-7).

Generated scripts call ``simagent_io.submit(answer, **data)`` exactly once. The result is written
as JSON to ``$SIMAGENT_OUT_DIR/result.json`` (``/out/result.json`` in the sandbox).

When provenance recording is on (``PHOTONSIM_TRACE=1``, set by the sandbox image), ``submit``
first writes photonsim's record of every simulation call to ``trace.json`` in the same directory,
replacing any file of that name the script may have written (R-TRACE-1, R-TRACE-3).

This module is standalone (standard library only) because it is copied into the sandbox image.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

__all__ = ["MAX_RESULT_BYTES", "submit"]

MAX_RESULT_BYTES = 1_000_000
TRACE_FLAG = "PHOTONSIM_TRACE"
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


def _trace_snapshot() -> dict[str, Any] | None:
    """photonsim's provenance record, or None when recording is off."""
    if os.environ.get(TRACE_FLAG) != "1":
        return None
    module = sys.modules.get("photonsim._provenance")
    if module is None:  # photonsim was never imported: nothing was simulated
        return {"version": 1, "enabled": True, "n_calls": 0, "truncated": False, "calls": []}
    snapshot: dict[str, Any] = module.recorder().snapshot()
    return snapshot


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
    trace = _trace_snapshot()
    if trace is not None:  # written first, so a result.json always has its trace beside it
        _write_atomic(out_dir / "trace.json", json.dumps(trace, allow_nan=False))
    _write_atomic(out_dir / "result.json", text)
    _submitted = True

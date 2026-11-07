"""Writer for per-run artifacts in ``runs/<timestamp>-<id>/`` (R-AG-7).

Layout::

    runs/20261107T101500Z-3fa2c1/
      attempt_1/reply.md, script.py, stdout.txt, stderr.txt, result.json, files/*.png
      attempt_2/...
      final.json     the final answer
      trace.json     request, settings, per-attempt outcome, timings and token counts

``runs/`` is gitignored.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from simagent.nodes import AttemptHook
from simagent.state import AgentState, AttemptRecord, FinalAnswer


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _json(path: Path, data: Any) -> None:
    _write(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def _safe_name(name: str) -> str | None:
    """A plain file name (no directories), else None."""
    candidate = Path(name).name
    if candidate != name or candidate in {"", ".", ".."}:
        return None
    return candidate


class ArtifactWriter(AttemptHook):
    """Writes each attempt as it finishes, then ``final.json`` and ``trace.json``."""

    def __init__(self, runs_dir: Path, run_meta: dict[str, Any] | None = None) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = Path(runs_dir) / f"{stamp}-{secrets.token_hex(3)}"
        self.dir.mkdir(parents=True, exist_ok=False)
        self.meta = dict(run_meta or {})
        self.started = datetime.now(UTC)

    def on_attempt(self, attempt: AttemptRecord) -> None:
        d = self.dir / f"attempt_{attempt['number']}"
        d.mkdir(parents=True, exist_ok=True)
        _write(d / "reply.md", attempt["reply"])
        if attempt["code"] is not None:
            _write(d / "script.py", attempt["code"])
        if attempt["error"]:
            _write(d / "error.txt", attempt["error"])
        run = attempt["run"]
        if run is not None:
            _write(d / "stdout.txt", run["stdout"])
            _write(d / "stderr.txt", run["stderr"])
            if run["result"] is not None:
                _json(d / "result.json", run["result"])
            for name, b64 in (run.get("files") or {}).items():
                safe = _safe_name(name)
                if safe is None:
                    continue
                try:
                    data = base64.b64decode(b64, validate=True)
                except (binascii.Error, ValueError):
                    continue
                (d / "files").mkdir(exist_ok=True)
                (d / "files" / safe).write_bytes(data)

    def on_final(self, state: AgentState, final: FinalAnswer) -> None:
        _json(self.dir / "final.json", {**final, "files": sorted(final["files"])})
        attempts = []
        for a in state["attempts"]:
            run = a["run"]
            attempts.append(
                {
                    "number": a["number"],
                    "kind": a["kind"],
                    "outcome": a["outcome"],
                    "error": a["error"],
                    "policy_violations": a["policy_violations"],
                    "model_s": a["model_s"],
                    "run_s": a["run_s"],
                    "metrics": a["metrics"],
                    "run": None
                    if run is None
                    else {
                        "runner": run["runner"],
                        "exit_code": run["exit_code"],
                        "timed_out": run["timed_out"],
                        "duration_s": run["duration_s"],
                        "files": sorted(run.get("files") or {}),
                    },
                }
            )
        trace = {
            "run_dir": self.dir.name,
            "started_utc": self.started.isoformat(),
            "finished_utc": datetime.now(UTC).isoformat(),
            "request": state["request"],
            "max_attempts": state["max_attempts"],
            "status": final["status"],
            **self.meta,
            "totals": final["metrics"],
            "attempts": attempts,
        }
        _json(self.dir / "trace.json", trace)

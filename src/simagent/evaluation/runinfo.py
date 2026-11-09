"""Facts about a run's environment for results headers (R-STAT-2): code commit, model digest.

Both are best effort: a value that cannot be determined is ``None``, never guessed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

FetchJson = Callable[[str], Any]


def code_commit(root: Path) -> str | None:
    """``git rev-parse HEAD`` (12 chars), with ``-dirty`` if tracked files are modified."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        head = subprocess.run(
            [git, "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if head.returncode != 0 or not head.stdout.strip():
            return None
        status = subprocess.run(
            [git, "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    dirty = status.returncode == 0 and bool(status.stdout.strip())
    return head.stdout.strip() + ("-dirty" if dirty else "")


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_model_info(
    base_url: str, model: str, fetch: FetchJson = _fetch_json
) -> dict[str, str | None] | None:
    """Digest and quantisation of a pulled Ollama model, from ``/api/tags``; None if unknown."""
    try:
        data = fetch(base_url.rstrip("/") + "/api/tags")
    except (OSError, urllib.error.URLError, ValueError):
        return None
    wanted = {model, model if ":" in model else f"{model}:latest"}
    for entry in data.get("models", []) if isinstance(data, dict) else []:
        if entry.get("name") in wanted or entry.get("model") in wanted:
            details = entry.get("details") or {}
            return {
                "digest": entry.get("digest"),
                "quantization": details.get("quantization_level"),
                "parameter_size": details.get("parameter_size"),
            }
    return None

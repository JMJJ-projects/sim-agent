"""Launcher that runs inside the sandbox container (standard library only).

Copied into the image as ``/opt/simagent/launch.py``. Runs ``/sandbox/script.py`` as a child
process with inherited stdout/stderr, then prints one JSON envelope after a marker line that
contains the per-run nonce given as ``argv[1]``::

    {"result_text": <result.json content or null>, "result_too_large": <bytes or null>,
     "files": {"plot.png": "<base64>", ...}, "skipped_files": ["big.png", ...]}

Only PNG files directly in ``/out`` are returned, smallest first, at most ``MAX_FILES_BYTES``
in total. The host takes the *last* marker, so output printed by the script cannot hide the real
envelope (and a script forging one gains nothing it could not get from ``simagent_io.submit``).
The exit code is the script's exit code.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

MARKER = "<<<SIMAGENT_RESULT:"
MAX_RESULT_BYTES = 1_000_000
MAX_FILES_BYTES = 1_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
OUT_DIR = Path("/out")
SCRIPT = Path("/sandbox/script.py")


def collect_pngs(out_dir: Path, budget: int = MAX_FILES_BYTES) -> tuple[dict[str, str], list[str]]:
    """Base64 PNGs directly in ``out_dir`` (no symlinks), smallest first, within ``budget``."""
    candidates: list[tuple[int, str, Path]] = []
    for path in out_dir.glob("*.png"):
        if path.is_symlink() or not path.is_file():
            continue
        candidates.append((path.stat().st_size, path.name, path))
    files: dict[str, str] = {}
    skipped: list[str] = []
    used = 0
    for size, name, path in sorted(candidates):
        if used + size > budget:
            skipped.append(name)
            continue
        data = path.read_bytes()
        if not data.startswith(PNG_MAGIC):
            skipped.append(name)
            continue
        files[name] = base64.b64encode(data).decode("ascii")
        used += size
    return files, sorted(skipped)


def envelope(out_dir: Path) -> dict[str, object]:
    """The JSON envelope describing what the script left in ``out_dir``."""
    result = out_dir / "result.json"
    text: str | None = None
    too_large: int | None = None
    if result.is_file() and not result.is_symlink():
        size = result.stat().st_size
        if size > MAX_RESULT_BYTES:
            too_large = size
        else:
            text = result.read_text(encoding="utf-8", errors="replace")
    files, skipped = collect_pngs(out_dir)
    return {
        "result_text": text,
        "result_too_large": too_large,
        "files": files,
        "skipped_files": skipped,
    }


def main() -> int:  # pragma: no cover - runs inside the container (tests/test_sandbox.py)
    nonce = sys.argv[1] if len(sys.argv) > 1 else "none"
    proc = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)], cwd="/tmp", check=False)
    sys.stdout.flush()
    sys.stdout.write(f"\n{MARKER}{nonce}>>>\n{json.dumps(envelope(OUT_DIR))}")
    sys.stdout.flush()
    # A child killed by a signal reports -N; use the shell convention 128 + N.
    return proc.returncode if proc.returncode >= 0 else 128 - proc.returncode


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

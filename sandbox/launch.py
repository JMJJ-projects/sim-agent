"""Launcher that runs inside the sandbox container (standard library only).

Runs ``/sandbox/script.py`` as a child process with inherited stdout/stderr, then, if the
script wrote ``/out/result.json``, prints it after a marker line containing the per-run nonce
given as ``argv[1]``. The host takes the *last* marker, so output printed by the script cannot
hide a real result (and a script forging its own result gains nothing it could not get from
``simagent_io.submit``). The exit code is the script's exit code.
"""

import subprocess
import sys
from pathlib import Path

MARKER = "<<<SIMAGENT_RESULT:"
MAX_RESULT_BYTES = 1_000_000


def main() -> int:
    nonce = sys.argv[1] if len(sys.argv) > 1 else "none"
    proc = subprocess.run([sys.executable, "-I", "-B", "/sandbox/script.py"], cwd="/tmp")
    sys.stdout.flush()
    result = Path("/out/result.json")
    if result.is_file():
        size = result.stat().st_size
        if size > MAX_RESULT_BYTES:
            body = f'{{"__too_large__": {size}}}'
        else:
            body = result.read_text(encoding="utf-8", errors="replace")
        sys.stdout.write(f"\n{MARKER}{nonce}>>>\n{body}")
        sys.stdout.flush()
    # A child killed by a signal reports -N; use the shell convention 128 + N.
    return proc.returncode if proc.returncode >= 0 else 128 - proc.returncode


if __name__ == "__main__":
    sys.exit(main())

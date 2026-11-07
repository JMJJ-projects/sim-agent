"""Unsafe local subprocess runner, for development only (R-SBX-8).

Runs the script with the host Python in a temporary directory. There is **no isolation**: no
network block, no filesystem protection, no resource limits beyond the timeout. It is disabled
unless explicitly enabled (``--unsafe-local`` or ``SIMAGENT_UNSAFE_LOCAL=1``), prints a warning
on every run, and is never used by the evaluation harness.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import photonsim
from simagent.runners.base import (
    DEFAULT_TIMEOUT_S,
    Runner,
    RunnerUnavailableError,
    RunResult,
    SandboxLimits,
    TailReader,
    cap_text,
    parse_result,
)

ENV_FLAG = "SIMAGENT_UNSAFE_LOCAL"
WARNING = (
    "WARNING: unsafe local runner: generated code runs on this machine WITHOUT isolation "
    "(no network block, no filesystem protection). Development only."
)
_IO_HELPER_DIR = Path(__file__).resolve().parents[1] / "io_helper"
_PHOTONSIM_PARENT = Path(photonsim.__file__).resolve().parents[1]
# Variables Python itself needs on Windows; nothing else from the host is passed on.
_WINDOWS_KEEP = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")


def unsafe_local_enabled(flag: bool = False) -> bool:
    """True when the local runner was explicitly enabled by flag or environment."""
    return flag or os.environ.get(ENV_FLAG, "").strip() == "1"


class LocalRunner(Runner):
    """Plain subprocess with a timeout. No isolation; development only."""

    name = "local-unsafe"

    def __init__(self, limits: SandboxLimits | None = None, *, enabled: bool = False) -> None:
        if not unsafe_local_enabled(enabled):
            raise RunnerUnavailableError(
                f"the unsafe local runner is disabled; pass --unsafe-local or set {ENV_FLAG}=1 "
                "(development only, no isolation)"
            )
        super().__init__(limits)

    def _env(self, out_dir: Path) -> dict[str, str]:
        env = {
            "SIMAGENT_OUT_DIR": str(out_dir),
            "PYTHONPATH": os.pathsep.join([str(_IO_HELPER_DIR), str(_PHOTONSIM_PARENT)]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "MPLBACKEND": "Agg",
        }
        if sys.platform == "win32":
            env.update({k: os.environ[k] for k in _WINDOWS_KEEP if k in os.environ})
        return env

    def run(self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> RunResult:
        print(WARNING, file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix="simagent-local-") as tmp:
            work = Path(tmp)
            out_dir = work / "out"
            out_dir.mkdir()
            script = work / "script.py"
            script.write_text(code, encoding="utf-8", newline="\n")
            env = self._env(out_dir)
            env["MPLCONFIGDIR"] = str(work / "mpl")
            start = time.monotonic()
            proc = subprocess.Popen(
                [sys.executable, "-B", str(script)],
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None
            assert proc.stderr is not None
            out = TailReader(proc.stdout, self.limits.output_cap * 4)
            err = TailReader(proc.stderr, self.limits.output_cap * 4)
            timed_out = False
            try:
                exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                exit_code = proc.wait()
            duration = time.monotonic() - start
            stdout, stderr = out.text(), err.text()
            result_path = out_dir / "result.json"
            result, result_error = (
                parse_result(result_path.read_text(encoding="utf-8"))
                if result_path.is_file()
                else (None, None)
            )
        if timed_out:
            stderr += f"\n[killed after the {timeout_s:g} s time limit]"
        return RunResult(
            exit_code=exit_code,
            stdout=cap_text(stdout.replace("\r\n", "\n"), self.limits.output_cap),
            stderr=cap_text(stderr.replace("\r\n", "\n"), self.limits.output_cap),
            result_json=result,
            timed_out=timed_out,
            duration_s=duration,
            result_error=result_error,
            runner=self.name,
            warnings=[WARNING],
        )

"""Docker-based sandbox runner (R-SBX-2 to R-SBX-6).

Uses the ``docker`` CLI through ``subprocess`` (no Docker SDK). Every container gets the
hardening flags of R-SBX-3; see ``DockerRunner.command``.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from simagent.io_helper.launch import MAX_FILES_BYTES
from simagent.runners.base import (
    DEFAULT_TIMEOUT_S,
    MAX_RESULT_BYTES,
    Collected,
    Runner,
    RunnerUnavailableError,
    RunResult,
    SandboxLimits,
    TailReader,
    cap_text,
    split_output,
)

# Bump the tag whenever the image contents change, so a stale image fails fast ("not built")
# instead of running old code. 2: provenance recording (PHOTONSIM_TRACE=1, trace.json).
IMAGE = "simagent-sandbox:2"
SANDBOX_UID = 10001
# Keep enough raw stdout to recover the launcher envelope printed after the script's output:
# result.json (<= 1 MB) plus base64 PNGs (<= 1 MB raw, ~1.34 MB encoded) plus slack.
_RAW_STDOUT_LIMIT = MAX_RESULT_BYTES + MAX_FILES_BYTES * 4 // 3 + 512 * 1024
_DAEMON_ERRORS = ("Cannot connect to the Docker daemon", "error during connect")


def docker_executable() -> str | None:
    """Path of the ``docker`` CLI, or None if it is not on PATH."""
    return shutil.which("docker")


def docker_status(image: str = IMAGE) -> tuple[bool, bool, str]:
    """Return (daemon reachable, image present, detail message)."""
    exe = docker_executable()
    if exe is None:
        return False, False, "docker CLI not found on PATH (install Docker Desktop / Docker Engine)"
    try:
        info = subprocess.run(
            [exe, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, False, f"docker daemon not reachable: {exc}"
    if info.returncode != 0:
        return False, False, "docker daemon not reachable (is Docker Desktop running?)"
    img = subprocess.run(
        [exe, "image", "inspect", image], capture_output=True, text=True, timeout=20
    )
    if img.returncode != 0:
        return True, False, f"image {image!r} not built (run `make sandbox-image`)"
    return True, True, f"docker {info.stdout.strip()}, image {image!r} present"


class DockerRunner(Runner):
    """Runs scripts in a locked-down, throw-away container."""

    name = "docker"

    def __init__(self, limits: SandboxLimits | None = None, image: str = IMAGE) -> None:
        super().__init__(limits)
        self.image = image

    def command(self, exe: str, container: str, script_dir: Path, nonce: str) -> list[str]:
        """The full ``docker run`` command line. All R-SBX-3 flags are mandatory."""
        lim = self.limits
        tmpfs_opts = "rw,noexec,nosuid,nodev"
        return [
            exe,
            "run",
            "--rm",
            "--name",
            container,
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:{tmpfs_opts},size={lim.tmp_mb}m",
            "--tmpfs",
            f"/out:{tmpfs_opts},size={lim.out_mb}m,uid={SANDBOX_UID},gid={SANDBOX_UID},mode=0700",
            "--memory",
            f"{lim.memory_mb}m",
            "--memory-swap",
            f"{lim.memory_mb}m",
            "--cpus",
            f"{lim.cpus:g}",
            "--pids-limit",
            str(lim.pids),
            "--user",
            f"{SANDBOX_UID}:{SANDBOX_UID}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--ipc",
            "none",
            "--ulimit",
            "nofile=256:256",
            "--mount",
            f"type=bind,source={script_dir.resolve()},target=/sandbox,readonly",
            "--entrypoint",
            "python",
            self.image,
            "-I",
            "-B",
            "/opt/simagent/launch.py",
            nonce,
        ]

    def run(self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> RunResult:
        exe = docker_executable()
        if exe is None:
            raise RunnerUnavailableError(
                "Docker is not available: the docker CLI was not found on PATH. "
                "Install Docker Desktop (WSL2) or Docker Engine, then run `make sandbox-image`."
            )
        container = f"simagent-{secrets.token_hex(8)}"
        nonce = secrets.token_hex(16)
        with tempfile.TemporaryDirectory(prefix="simagent-") as tmp:
            script_dir = Path(tmp)
            script = script_dir / "script.py"
            script.write_text(code, encoding="utf-8", newline="\n")
            # mkdtemp creates the dir as 0700 for the host user; the container's non-root user
            # (uid 10001) must be able to read the bind-mounted script on Linux. The mount stays
            # read-only, so this grants read access only (Docker Desktop on Windows ignores it).
            script_dir.chmod(0o755)
            script.chmod(0o644)
            cmd = self.command(exe, container, script_dir, nonce)
            start = time.monotonic()
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            assert proc.stdout is not None
            assert proc.stderr is not None
            out = TailReader(proc.stdout, _RAW_STDOUT_LIMIT)
            err = TailReader(proc.stderr, self.limits.output_cap * 4)
            timed_out = False
            try:
                exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill(exe, container)
                try:
                    exit_code = proc.wait(timeout=30)
                except subprocess.TimeoutExpired:  # pragma: no cover - docker CLI hung
                    proc.kill()
                    exit_code = proc.wait()
            duration = time.monotonic() - start
            raw_stdout, stderr = out.text(), err.text()

        if exit_code == 125 and "No such image" in stderr:
            raise RunnerUnavailableError(
                f"sandbox image {self.image!r} is not built; run `make sandbox-image`"
            )
        if exit_code != 0 and any(s in stderr for s in _DAEMON_ERRORS):
            raise RunnerUnavailableError(
                "the Docker daemon is not reachable; start Docker Desktop / dockerd"
            )
        stdout, collected = split_output(raw_stdout, nonce)
        collected = collected or Collected()
        if timed_out:
            stderr += f"\n[killed after the {timeout_s:g} s time limit]"
        elif exit_code == 137:
            stderr += (
                f"\n[killed: exit code 137, likely the {self.limits.memory_mb} MB memory limit]"
            )
        return RunResult(
            exit_code=exit_code,
            stdout=cap_text(stdout, self.limits.output_cap),
            stderr=cap_text(stderr, self.limits.output_cap),
            result_json=collected.result,
            timed_out=timed_out,
            duration_s=duration,
            result_error=collected.error,
            runner=self.name,
            warnings=collected.warnings,
            files=collected.files,
            trace=collected.trace,
        )

    @staticmethod
    def _kill(exe: str, container: str) -> None:
        subprocess.run([exe, "kill", container], capture_output=True, timeout=30, check=False)

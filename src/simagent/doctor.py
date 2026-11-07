"""Environment health checks for ``simagent doctor`` (R-CLI-3)."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from simagent.config import Settings
from simagent.runners.docker import docker_status


@dataclass(frozen=True)
class Check:
    """One check line. ``required`` failures make ``doctor`` exit with code 2."""

    name: str
    ok: bool
    detail: str
    required: bool = False


def check_docker() -> list[Check]:
    daemon, image, detail = docker_status()
    if not daemon:
        return [Check("docker", False, detail, required=True)]
    return [
        Check("docker", True, "daemon reachable", required=True),
        Check("sandbox image", image, detail, required=True),
    ]


def ollama_models(base_url: str, timeout: float = 3.0) -> list[str]:
    """Names of the models pulled in the Ollama server at ``base_url``."""
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return sorted(str(m.get("name", "?")) for m in data.get("models", []))


def check_ollama(base_url: str) -> Check:
    try:
        models = ollama_models(base_url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Check("ollama", False, f"not reachable at {base_url} ({exc})")
    listed = ", ".join(models) if models else "no models pulled (try `ollama pull <tag>`)"
    return Check("ollama", True, f"{base_url}: {listed}")


def check_gpu() -> Check:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return Check("gpu", False, "nvidia-smi not found (CPU only)")
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("gpu", False, f"nvidia-smi failed: {exc}")
    if out.returncode != 0 or not out.stdout.strip():
        return Check("gpu", False, "nvidia-smi found but no GPU reported")
    return Check("gpu", True, "; ".join(line.strip() for line in out.stdout.splitlines()))


def check_keys() -> list[Check]:
    return [
        Check(name, present, "present" if present else "absent")
        for name, present in Settings.key_status().items()
    ]


def run_checks(settings: Settings) -> list[Check]:
    return [*check_docker(), check_ollama(settings.ollama_base_url), check_gpu(), *check_keys()]

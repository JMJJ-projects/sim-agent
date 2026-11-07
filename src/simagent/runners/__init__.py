"""Runners: the only way generated code is executed (R-SBX-1)."""

from simagent.runners.base import (
    DEFAULT_TIMEOUT_S,
    Runner,
    RunnerUnavailableError,
    RunResult,
    SandboxLimits,
)
from simagent.runners.docker import DockerRunner
from simagent.runners.local import LocalRunner, unsafe_local_enabled


def make_runner(*, unsafe_local: bool = False, limits: SandboxLimits | None = None) -> Runner:
    """Return the configured runner: Docker by default, the unsafe local runner only on opt-in."""
    if unsafe_local_enabled(unsafe_local):
        return LocalRunner(limits, enabled=True)
    return DockerRunner(limits)


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "DockerRunner",
    "LocalRunner",
    "RunResult",
    "Runner",
    "RunnerUnavailableError",
    "SandboxLimits",
    "make_runner",
]

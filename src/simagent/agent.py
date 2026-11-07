"""Assemble the agent from configuration: shared by the CLI, the MCP server and the evaluation.

Pre-flight checks turn a missing sandbox or an unreachable/missing local model into one clear
configuration error before any model call (CLI exit code 2).
"""

from __future__ import annotations

import urllib.error
from collections.abc import Sequence
from pathlib import Path

from simagent.artifacts import ArtifactWriter
from simagent.config import ConfigError, Settings
from simagent.doctor import ollama_models
from simagent.graph import solve
from simagent.llm import make_chat_model, resolve_model
from simagent.nodes import AgentDeps, AttemptHook
from simagent.runners import DockerRunner, Runner, RunnerUnavailableError, make_runner
from simagent.runners.docker import docker_status
from simagent.state import FinalAnswer

MAX_ATTEMPTS_LIMIT = 10


def check_runner(runner: Runner) -> None:
    """Raise ``RunnerUnavailableError`` if the Docker sandbox cannot be used."""
    if isinstance(runner, DockerRunner):
        daemon, image, detail = docker_status(runner.image)
        if not (daemon and image):
            raise RunnerUnavailableError(f"sandbox not available: {detail}")


def check_model(settings: Settings) -> None:
    """For Ollama: the server must answer and the model must be pulled."""
    if settings.provider != "ollama":
        return
    model = resolve_model(settings)
    try:
        pulled = ollama_models(settings.ollama_base_url)
    except (urllib.error.URLError, OSError, ValueError):
        raise ConfigError(
            f"Ollama is not reachable at {settings.ollama_base_url}; start it (`ollama serve`)"
        ) from None
    names = set(pulled) | {p.removesuffix(":latest") for p in pulled}
    if model not in names:
        raise ConfigError(f"Ollama model {model!r} is not pulled; run `ollama pull {model}`")


def validate_max_attempts(max_attempts: int) -> int:
    if not 1 <= max_attempts <= MAX_ATTEMPTS_LIMIT:
        raise ConfigError(f"max attempts must be between 1 and {MAX_ATTEMPTS_LIMIT}")
    return max_attempts


def build_deps(
    settings: Settings,
    *,
    unsafe_local: bool = False,
    fake_replies: Sequence[str] | None = None,
    hooks: Sequence[AttemptHook] = (),
    preflight: bool = True,
) -> AgentDeps:
    """Model, runner and limits from configuration (never from the model, R-AG-8)."""
    runner = make_runner(unsafe_local=unsafe_local, limits=settings.limits)
    if preflight:
        check_runner(runner)
        check_model(settings)
    return AgentDeps(
        model=make_chat_model(settings, fake_replies=fake_replies),
        runner=runner,
        provider=settings.provider,
        model_name=resolve_model(settings),
        timeout_s=settings.timeout_s,
        prompt_version=settings.prompt_version,
        hooks=list(hooks),
    )


def run_agent(
    request: str,
    settings: Settings,
    *,
    max_attempts: int,
    unsafe_local: bool = False,
    save_artifacts: bool = True,
    runs_dir: Path | None = None,
) -> tuple[FinalAnswer, Path | None]:
    """Solve ``request``; returns the final answer and the artifact directory (if saved)."""
    validate_max_attempts(max_attempts)
    writer: ArtifactWriter | None = None
    deps = build_deps(settings, unsafe_local=unsafe_local)
    if save_artifacts:
        writer = ArtifactWriter(
            runs_dir or settings.runs_dir,
            {"provider": deps.provider, "model": deps.model_name, "runner": deps.runner.name},
        )
        deps.hooks.append(writer)
    final = solve(request, deps, max_attempts=max_attempts)
    return final, (writer.dir if writer else None)

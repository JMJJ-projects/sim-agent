"""Configuration from environment and ``.env`` (R-LLM-4).

Keys are read from the environment only and are never printed; ``Settings.key_status`` reports
presence. Sandbox limits and timeouts come from here, never from the model (R-AG-8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from simagent.runners.base import DEFAULT_TIMEOUT_S, SandboxLimits

PROVIDERS = ("ollama", "groq", "openai", "fake")
KEY_VARS = ("GROQ_API_KEY", "OPENAI_API_KEY")
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class ConfigError(ValueError):
    """Invalid configuration or input (CLI exit code 2)."""


def load_env() -> None:
    """Load ``.env`` from the current directory upwards, without overriding real variables."""
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one invocation."""

    provider: str = "ollama"
    model: str = ""
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_attempts: int = 4
    runs_dir: Path = Path("runs")
    limits: SandboxLimits = field(default_factory=SandboxLimits)

    @classmethod
    def from_env(cls, *, provider: str | None = None, model: str | None = None) -> Settings:
        prov = (provider or _env("LLM_PROVIDER", "ollama")).lower()
        if prov not in PROVIDERS:
            raise ConfigError(f"unknown provider {prov!r}; choose one of {', '.join(PROVIDERS)}")
        return cls(
            provider=prov,
            model=model or _env("LLM_MODEL"),
            ollama_base_url=_env("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
            runs_dir=Path(_env("SIMAGENT_RUNS_DIR", "runs")),
        )

    @staticmethod
    def key_status() -> dict[str, bool]:
        """Which API keys are set (values are never returned)."""
        return {name: bool(os.environ.get(name, "").strip()) for name in KEY_VARS}

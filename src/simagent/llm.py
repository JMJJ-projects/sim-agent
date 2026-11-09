"""LLM provider factory and the scripted fake provider (R-LLM-1, R-LLM-2).

All providers return a LangChain ``BaseChatModel``. Integration packages are optional extras and
imported lazily, so a missing extra is a configuration error with an install hint.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr

from simagent.config import ConfigError, Settings

DEFAULT_MODELS = {"ollama": "qwen2.5-coder:3b", "fake": "scripted"}


class FakeExhaustedError(RuntimeError):
    """The scripted fake model was called more often than it has replies."""


class ScriptedChatModel(BaseChatModel):
    """Replays a fixed list of replies in order; raises when they run out (R-LLM-2).

    Streams each reply in a few chunks so callers exercise the same code path as real models.
    It reports no token usage, so metrics record ``null`` for tokens (R-LLM-3).
    """

    replies: list[str]
    _index: int = PrivateAttr(default=0)
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        """The message lists this model has been called with, in order."""
        return self._calls

    @property
    def remaining(self) -> int:
        return len(self.replies) - self._index

    def _next(self, messages: list[BaseMessage]) -> str:
        if self._index >= len(self.replies):
            raise FakeExhaustedError(
                f"scripted fake model has no reply left (it had {len(self.replies)})"
            )
        self._calls.append(list(messages))
        reply = self.replies[self._index]
        self._index += 1
        return reply

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = self._next(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = self._next(messages)
        for piece in _split(text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))


def _split(text: str, size: int = 64) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _require_key(var: str, provider: str) -> None:
    if not os.environ.get(var, "").strip():
        raise ConfigError(f"provider {provider!r} needs {var} in the environment or .env")


def _missing_extra(provider: str) -> ConfigError:
    return ConfigError(
        f'provider {provider!r} needs its integration package: pip install -e ".[{provider}]"'
    )


def resolve_model(settings: Settings) -> str:
    """The model name to use: explicit setting, else the provider default, else an error."""
    if settings.model:
        return settings.model
    if settings.provider in DEFAULT_MODELS:
        return DEFAULT_MODELS[settings.provider]
    raise ConfigError(
        f"provider {settings.provider!r} needs a model: pass --model or set LLM_MODEL"
    )


# Whether the provider accepts a sampling seed (R-STAT-2). Groq and OpenAI document it as best
# effort; the fake provider is scripted, so a seed means nothing there.
SEED_SUPPORTED = {"ollama": True, "groq": True, "openai": True, "fake": False}


def seed_supported(provider: str) -> bool:
    return SEED_SUPPORTED.get(provider, False)


def make_chat_model(
    settings: Settings, *, fake_replies: Sequence[str] | None = None
) -> BaseChatModel:
    """Build the chat model for ``settings.provider`` (R-LLM-1)."""
    provider = settings.provider
    model = resolve_model(settings)
    if provider == "fake":
        if fake_replies is None:
            from simagent.demo import DEMO_REPLIES

            fake_replies = DEMO_REPLIES
        return ScriptedChatModel(replies=list(fake_replies))
    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise _missing_extra("ollama") from None
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            num_ctx=settings.num_ctx,
            temperature=settings.temperature,
            seed=settings.llm_seed,
            # Bound runaway generations (observed: endless repetition on an adversarial task).
            num_predict=settings.max_output_tokens,
        )
    if provider == "groq":
        _require_key("GROQ_API_KEY", provider)
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise _missing_extra("groq") from None
        # ChatGroq has no ``seed`` field; the Groq API accepts ``seed`` (best effort, not
        # guaranteed deterministic), so it goes through ``model_kwargs`` (see NOTES.md).
        return ChatGroq(
            model=model,
            temperature=settings.temperature,
            model_kwargs={"seed": settings.llm_seed},
            max_retries=2,
        )
    if provider == "openai":
        _require_key("OPENAI_API_KEY", provider)
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise _missing_extra("openai") from None
        return ChatOpenAI(
            model=model,
            temperature=settings.temperature,
            seed=settings.llm_seed,
            stream_usage=True,
            max_retries=2,
        )
    raise ConfigError(f"unknown provider {provider!r}")  # pragma: no cover - validated earlier

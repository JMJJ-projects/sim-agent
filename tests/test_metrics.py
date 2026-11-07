"""Tests for per-call metrics with fake streaming models and a fake clock."""

from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from simagent.llm import ScriptedChatModel
from simagent.metrics import stream_with_metrics


class ChunkModel(BaseChatModel):
    """Streams pre-built chunks."""

    chunks: list[AIMessageChunk]

    @property
    def _llm_type(self) -> str:
        return "chunks"

    def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
        raise NotImplementedError

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for c in self.chunks:
            yield ChatGenerationChunk(message=c)


class Clock:
    """Advances by fixed steps on each call."""

    def __init__(self, times: list[float]) -> None:
        self.times = iter(times)

    def __call__(self) -> float:
        return next(self.times)


USAGE = {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}


def _run(chunks: list[AIMessageChunk], times: list[float]) -> Any:
    return stream_with_metrics(
        ChunkModel(chunks=chunks),
        [HumanMessage("hi")],
        provider="test",
        model_name="m",
        clock=Clock(times),
    )


def test_measured_throughput_and_ttft() -> None:
    """Covers R-LLM-3."""
    chunks = [
        AIMessageChunk(content=""),
        AIMessageChunk(content="Hello "),
        AIMessageChunk(content="world", usage_metadata=USAGE),  # type: ignore[arg-type]
    ]
    # clock: start=0, first text at 0.5, end at 2.5
    text, m = _run(chunks, [0.0, 0.5, 2.5])
    assert text == "Hello world"
    assert m.ttft_s == pytest.approx(0.5)
    assert m.latency_s == pytest.approx(2.5)
    assert (m.input_tokens, m.output_tokens) == (120, 40)
    assert m.tokens_per_s == pytest.approx(40 / 2.0)
    assert m.tokens_per_s_source == "measured"


def test_provider_reported_throughput_preferred() -> None:
    """Covers R-LLM-3: Ollama's eval_count / eval_duration."""
    chunks = [
        AIMessageChunk(content="x"),
        AIMessageChunk(
            content="",
            usage_metadata=USAGE,  # type: ignore[arg-type]
            response_metadata={"eval_count": 40, "eval_duration": 800_000_000},
        ),
    ]
    _, m = _run(chunks, [0.0, 0.1, 3.0])
    assert m.tokens_per_s == pytest.approx(50.0)
    assert m.tokens_per_s_source == "provider"


def test_unreported_values_are_none() -> None:
    """Covers R-LLM-3: no usage reported means null, never a guess."""
    text, m = stream_with_metrics(
        ScriptedChatModel(replies=["some reply"]),
        [HumanMessage("hi")],
        provider="fake",
        model_name="scripted",
    )
    assert text == "some reply"
    assert m.input_tokens is None
    assert m.output_tokens is None
    assert m.tokens_per_s is None
    assert m.tokens_per_s_source is None
    assert m.ttft_s is not None
    d = m.to_dict()
    assert d["output_tokens"] is None
    assert d["provider"] == "fake"


def test_empty_reply_has_no_ttft() -> None:
    _, m = _run([AIMessageChunk(content="")], [0.0, 1.0])
    assert m.ttft_s is None
    assert m.tokens_per_s is None


def test_zero_generation_time_gives_none() -> None:
    chunks = [AIMessageChunk(content="x", usage_metadata=USAGE)]  # type: ignore[arg-type]
    _, m = _run(chunks, [0.0, 1.0, 1.0])
    assert m.tokens_per_s is None

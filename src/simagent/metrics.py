"""Per-call model metrics: tokens, time to first token, latency, throughput (R-LLM-3).

Every model call goes through ``stream_with_metrics``, which streams the reply so time to first
token (TTFT) is measured on the client. Token counts come only from what the provider reports;
when it reports nothing, the value is ``None`` (``null`` in JSON), never an estimate.

Output tokens per second:

* ``"provider"``: from the provider's own generation timing when available (Ollama reports
  ``eval_count`` and ``eval_duration``), which excludes model loading and prompt processing.
* ``"measured"``: ``output_tokens / (latency - ttft)``, i.e. reported tokens over the measured
  streaming time after the first token.
* ``None`` when the provider reports no output token count.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage


@dataclass(frozen=True)
class CallMetrics:
    """Metrics for one model call. ``None`` means "not reported"."""

    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    ttft_s: float | None
    latency_s: float
    tokens_per_s: float | None
    tokens_per_s_source: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _throughput(
    output_tokens: int | None,
    ttft_s: float | None,
    latency_s: float,
    response_metadata: dict[str, Any],
) -> tuple[float | None, str | None]:
    eval_count = _int_or_none(response_metadata.get("eval_count"))
    eval_ns = _int_or_none(response_metadata.get("eval_duration"))
    if eval_count is not None and eval_ns:
        return eval_count / (eval_ns / 1e9), "provider"
    if output_tokens is None or ttft_s is None:
        return None, None
    gen_time = latency_s - ttft_s
    if gen_time <= 0:
        return None, None
    return output_tokens / gen_time, "measured"


def stream_with_metrics(
    model: BaseChatModel,
    messages: Sequence[BaseMessage],
    *,
    provider: str,
    model_name: str,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[str, CallMetrics]:
    """Stream one reply from ``model`` and return ``(text, metrics)``."""
    start = clock()
    ttft: float | None = None
    merged: AIMessageChunk | None = None
    for chunk in model.stream(list(messages)):
        if not isinstance(chunk, AIMessageChunk):  # pragma: no cover - defensive
            continue
        if ttft is None and chunk.text:
            ttft = clock() - start
        merged = chunk if merged is None else merged + chunk
    latency = clock() - start
    text = merged.text if merged is not None else ""
    usage = merged.usage_metadata if merged is not None else None
    input_tokens = _int_or_none(usage.get("input_tokens")) if usage else None
    output_tokens = _int_or_none(usage.get("output_tokens")) if usage else None
    meta = dict(merged.response_metadata) if merged is not None else {}
    tps, source = _throughput(output_tokens, ttft, latency, meta)
    return text, CallMetrics(
        provider=provider,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        ttft_s=ttft,
        latency_s=latency,
        tokens_per_s=tps,
        tokens_per_s_source=source,
    )

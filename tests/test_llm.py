"""Tests for the provider factory and the scripted fake model."""

import pytest
from langchain_core.messages import HumanMessage

from simagent.config import ConfigError, Settings
from simagent.demo import DEMO_REPLIES
from simagent.llm import FakeExhaustedError, ScriptedChatModel, make_chat_model, resolve_model


def test_fake_replays_in_order_then_raises() -> None:
    """Covers R-LLM-2."""
    model = ScriptedChatModel(replies=["one", "two"])
    assert model.invoke("a").content == "one"
    assert "".join(str(c.content) for c in model.stream("b")) == "two"
    assert model.remaining == 0
    with pytest.raises(FakeExhaustedError, match="no reply left"):
        model.invoke("c")
    assert [m[0].content for m in model.calls] == ["a", "b"]


def test_fake_streams_in_several_chunks() -> None:
    model = ScriptedChatModel(replies=["x" * 200])
    chunks = list(model.stream([HumanMessage("hi")]))
    assert len(chunks) > 1


def test_fake_provider_defaults_to_demo_script() -> None:
    model = make_chat_model(Settings.from_env(provider="fake"))
    assert isinstance(model, ScriptedChatModel)
    assert model.replies == DEMO_REPLIES
    assert "H2O" in DEMO_REPLIES[0]
    assert '"water"' in DEMO_REPLIES[1]


def test_fake_provider_custom_replies() -> None:
    model = make_chat_model(Settings.from_env(provider="fake"), fake_replies=["r"])
    assert isinstance(model, ScriptedChatModel)
    assert model.replies == ["r"]


def test_ollama_model_is_configured_without_network() -> None:
    """Covers R-LLM-1: constructing the client does not contact the server."""
    from langchain_ollama import ChatOllama

    settings = Settings.from_env(provider="ollama", model="qwen2.5-coder:3b")
    model = make_chat_model(settings)
    assert isinstance(model, ChatOllama)
    assert model.model == "qwen2.5-coder:3b"
    assert model.num_ctx == settings.num_ctx
    assert model.temperature == 0.0
    assert model.num_predict == settings.max_output_tokens == 2048


@pytest.mark.parametrize(
    ("provider", "var"), [("groq", "GROQ_API_KEY"), ("openai", "OPENAI_API_KEY")]
)
def test_hosted_providers_need_keys(
    provider: str, var: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers R-LLM-4."""
    monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConfigError, match=var):
        make_chat_model(Settings.from_env(provider=provider, model="m"))


@pytest.mark.parametrize("provider", ["groq", "openai"])
def test_hosted_providers_build_with_key(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = make_chat_model(Settings.from_env(provider=provider, model="some-model"))
    assert type(model).__name__ in {"ChatGroq", "ChatOpenAI"}


def test_hosted_provider_needs_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ConfigError, match="needs a model"):
        resolve_model(Settings.from_env(provider="groq"))


def test_num_ctx_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMAGENT_NUM_CTX", "4096")
    assert Settings.from_env(provider="fake").num_ctx == 4096
    monkeypatch.setenv("SIMAGENT_NUM_CTX", "lots")
    with pytest.raises(ConfigError, match="integer"):
        Settings.from_env(provider="fake")
    monkeypatch.setenv("SIMAGENT_NUM_CTX", "0")
    with pytest.raises(ConfigError, match=">= 1"):
        Settings.from_env(provider="fake")


def test_seed_reaches_every_seeded_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers R-STAT-2: the sampling seed and temperature are passed to the provider."""
    from dataclasses import replace

    from simagent.llm import seed_supported

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    base = Settings.from_env(provider="groq", model="m")
    groq = make_chat_model(replace(base, temperature=0.7, llm_seed=3))
    assert groq._default_params["seed"] == 3  # type: ignore[attr-defined]
    assert groq._default_params["temperature"] == 0.7  # type: ignore[attr-defined]
    ollama = make_chat_model(replace(base, provider="ollama", llm_seed=4, temperature=0.7))
    assert ollama.seed == 4  # type: ignore[attr-defined]
    assert ollama.temperature == 0.7  # type: ignore[attr-defined]
    assert seed_supported("ollama")
    assert seed_supported("groq")
    assert not seed_supported("fake")
    assert not seed_supported("unknown")

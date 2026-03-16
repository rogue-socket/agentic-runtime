"""Tests for the LLM provider registry."""

from __future__ import annotations

from typing import Any, Dict

from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig


def test_register_and_lookup_provider() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="OPENAI_API_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4", temperature=0.2))
    registry.register_provider(provider)

    assert registry.list_providers() == ["openai"]
    assert registry.get_provider("openai") is provider


def test_get_model() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="anthropic", api_key_env="ANTHROPIC_API_KEY")
    provider.add_model(ModelConfig(model_id="claude-3-opus", temperature=0.3, max_tokens=8192))
    registry.register_provider(provider)

    model = registry.get_model("anthropic", "claude-3-opus")
    assert model is not None
    assert model.model_id == "claude-3-opus"
    assert model.temperature == 0.3
    assert model.max_tokens == 8192


def test_get_model_unknown_provider() -> None:
    registry = LLMRegistry()
    assert registry.get_model("nonexistent", "gpt-4") is None


def test_get_model_unknown_model() -> None:
    registry = LLMRegistry()
    registry.register_provider(LLMProvider(name="openai", api_key_env="KEY"))
    assert registry.get_model("openai", "nonexistent") is None


def test_list_all_models() -> None:
    registry = LLMRegistry()
    p1 = LLMProvider(name="openai", api_key_env="K1")
    p1.add_model(ModelConfig(model_id="gpt-4"))
    p1.add_model(ModelConfig(model_id="gpt-4o"))
    p2 = LLMProvider(name="local", api_key_env="K2")
    p2.add_model(ModelConfig(model_id="llama-3"))
    registry.register_provider(p1)
    registry.register_provider(p2)

    models = registry.list_all_models()
    assert set(models["openai"]) == {"gpt-4", "gpt-4o"}
    assert models["local"] == ["llama-3"]


def test_credential_resolution(monkeypatch: Any) -> None:
    provider = LLMProvider(name="openai", api_key_env="TEST_OPENAI_KEY_XYZ")
    assert provider.has_credentials() is False
    assert provider.resolve_api_key() is None

    monkeypatch.setenv("TEST_OPENAI_KEY_XYZ", "sk-test-123")
    assert provider.has_credentials() is True
    assert provider.resolve_api_key() == "sk-test-123"


def test_check_credentials(monkeypatch: Any) -> None:
    registry = LLMRegistry()
    registry.register_provider(LLMProvider(name="a", api_key_env="TEST_KEY_A"))
    registry.register_provider(LLMProvider(name="b", api_key_env="TEST_KEY_B"))

    monkeypatch.setenv("TEST_KEY_A", "val")
    creds = registry.check_credentials()
    assert creds["a"] is True
    assert creds["b"] is False


def test_from_config() -> None:
    config: Dict[str, Any] = {
        "providers": {
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "models": {
                    "gpt-4": {"temperature": 0.1, "max_tokens": 2048},
                    "gpt-4o": {},
                },
            },
            "local": {
                "api_key_env": "LOCAL_KEY",
                "base_url": "http://localhost:8080/v1",
                "models": {
                    "llama-3": {"temperature": 0.5},
                },
            },
        }
    }
    registry = LLMRegistry.from_config(config)
    assert set(registry.list_providers()) == {"openai", "local"}

    openai = registry.get_provider("openai")
    assert openai is not None
    assert openai.api_key_env == "OPENAI_API_KEY"
    gpt4 = openai.get_model("gpt-4")
    assert gpt4 is not None
    assert gpt4.temperature == 0.1
    assert gpt4.max_tokens == 2048

    local = registry.get_provider("local")
    assert local is not None
    assert local.base_url == "http://localhost:8080/v1"


def test_from_config_empty() -> None:
    registry = LLMRegistry.from_config({})
    assert registry.list_providers() == []


def test_remove_provider() -> None:
    registry = LLMRegistry()
    registry.register_provider(LLMProvider(name="x", api_key_env="K"))
    assert registry.list_providers() == ["x"]
    registry.remove_provider("x")
    assert registry.list_providers() == []


def test_to_dict() -> None:
    registry = LLMRegistry()
    p = LLMProvider(name="openai", api_key_env="KEY", base_url="http://x")
    p.add_model(ModelConfig(model_id="gpt-4", temperature=0.5, max_tokens=1000))
    registry.register_provider(p)

    d = registry.to_dict()
    assert "openai" in d
    assert d["openai"]["api_key_env"] == "KEY"
    assert d["openai"]["base_url"] == "http://x"
    assert "gpt-4" in d["openai"]["models"]
    assert d["openai"]["models"]["gpt-4"]["temperature"] == 0.5

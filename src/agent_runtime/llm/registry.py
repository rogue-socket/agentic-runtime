"""LLM provider registry.

Manages multiple LLM providers (OpenAI, Anthropic, local, etc.) with their
API credentials and model configurations.  The registry is the single source
of truth for which models are available to the runtime.

Credentials are resolved exclusively from environment variables — API keys
are never stored on disk or inside workflow YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """One model definition within a provider."""

    model_id: str                          # e.g. "gpt-4", "claude-3-opus"
    temperature: float = 0.2
    max_tokens: int = 4096
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d


@dataclass
class LLMProvider:
    """A registered LLM provider with credentials and available models."""

    name: str                                # e.g. "openai", "anthropic"
    api_key_env: str                         # env var name (e.g. OPENAI_API_KEY)
    base_url: Optional[str] = None           # custom endpoint for local/proxy
    models: Dict[str, ModelConfig] = field(default_factory=dict)

    # ---- credential resolution -----

    def resolve_api_key(self) -> Optional[str]:
        """Resolve the API key from the environment.  Never stored on disk."""
        return os.environ.get(self.api_key_env)

    def has_credentials(self) -> bool:
        return self.resolve_api_key() is not None

    # ---- model helpers -----

    def add_model(self, config: ModelConfig) -> None:
        self.models[config.model_id] = config

    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        return self.models.get(model_id)

    def list_models(self) -> List[str]:
        return list(self.models.keys())

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "api_key_env": self.api_key_env,
        }
        if self.base_url:
            d["base_url"] = self.base_url
        if self.models:
            d["models"] = {k: v.to_dict() for k, v in self.models.items()}
        return d


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class LLMRegistry:
    """Central registry of LLM providers and their model configurations.

    Usage::

        registry = LLMRegistry()
        registry.register_provider(LLMProvider(
            name="openai",
            api_key_env="OPENAI_API_KEY",
            models={"gpt-4": ModelConfig(model_id="gpt-4")},
        ))  

        provider = registry.get_provider("openai")
        model    = registry.get_model("openai", "gpt-4")

    The registry can also be populated from a YAML configuration section
    (typically inside ``runtime.yaml``).
    """

    def __init__(self) -> None:
        self._providers: Dict[str, LLMProvider] = {}

    # ---- registration -----

    def register_provider(self, provider: LLMProvider) -> None:
        self._providers[provider.name] = provider

    def remove_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    # ---- lookup -----

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self._providers.get(name)

    def get_model(self, provider_name: str, model_id: str) -> Optional[ModelConfig]:
        provider = self._providers.get(provider_name)
        if provider is None:
            return None
        return provider.get_model(model_id)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def list_all_models(self) -> Dict[str, List[str]]:
        """Return ``{provider_name: [model_id, …]}`` for every provider."""
        return {name: p.list_models() for name, p in self._providers.items()}

    # ---- credential status -----

    def check_credentials(self) -> Dict[str, bool]:
        """Return ``{provider_name: has_key}`` for a quick health check."""
        return {name: p.has_credentials() for name, p in self._providers.items()}

    # ---- serialization -----

    def to_dict(self) -> Dict[str, Any]:
        return {name: p.to_dict() for name, p in self._providers.items()}

    # ---- loading from config -----

    @classmethod
    def from_config(cls, llm_section: Dict[str, Any]) -> "LLMRegistry":
        """Build a registry from the ``llm`` section of ``runtime.yaml``.

        Expected shape::

            llm:
              providers:
                openai:
                  api_key_env: OPENAI_API_KEY
                  models:
                    gpt-4:
                      temperature: 0.2
                      max_tokens: 4096
                anthropic:
                  api_key_env: ANTHROPIC_API_KEY
                  base_url: https://api.anthropic.com
                  models:
                    claude-3-opus:
                      temperature: 0.3
        """
        registry = cls()
        providers_raw = llm_section.get("providers", {})
        if not isinstance(providers_raw, dict):
            return registry

        for provider_name, provider_data in providers_raw.items():
            if not isinstance(provider_data, dict):
                continue
            api_key_env = provider_data.get("api_key_env", "")
            base_url = provider_data.get("base_url")
            provider = LLMProvider(
                name=provider_name,
                api_key_env=api_key_env,
                base_url=base_url,
            )
            models_raw = provider_data.get("models", {})
            if isinstance(models_raw, dict):
                for model_id, model_data in models_raw.items():
                    if not isinstance(model_data, dict):
                        model_data = {}
                    provider.add_model(ModelConfig(
                        model_id=model_id,
                        temperature=float(model_data.get("temperature", 0.2)),
                        max_tokens=int(model_data.get("max_tokens", 4096)),
                        extra={k: v for k, v in model_data.items()
                               if k not in ("temperature", "max_tokens")},
                    ))
            registry.register_provider(provider)
        return registry

    @classmethod
    def from_yaml(cls, path: str) -> "LLMRegistry":
        """Load the ``llm`` section from a YAML file."""
        if not os.path.isfile(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict) or "llm" not in raw:
            return cls()
        return cls.from_config(raw["llm"])

"""Centralized configuration for model providers and models used by the benchmark."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ProviderConfig:
    """Represents the allowable models for a given provider."""

    identifier: str
    models: Tuple[str, ...]
    default_model: str

    def __post_init__(self) -> None:
        if self.default_model not in self.models:
            raise ValueError(
                f"Default model '{self.default_model}' must be within the provider model list for '{self.identifier}'."
            )


AVAILABLE_PROVIDERS: Dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        identifier="openai",
        models=("openai/gpt-4o", "openai/gpt-4o-mini", "openai/gpt-4.1-mini", "openai/gpt-4.1"),
        default_model="openai/gpt-4.1-mini",
    ),
    "deepseek": ProviderConfig(
        identifier="deepseek",
        models=("deepseek/deepseek-chat", "deepseek/deepseek-r1"),
        default_model="deepseek/deepseek-chat",
    ),
    "gemini": ProviderConfig(
        identifier="gemini",
        models=(
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
        ),
        default_model="google/gemini-2.5-pro",
    ),
    "ollama": ProviderConfig(
        identifier="ollama",
        models=("qwen3:8b", "qwen3:14b"),
        default_model="qwen3:8b",
    ),
}

DEFAULT_PROVIDER = "openai"


class ConfigurationError(ValueError):
    """Raised when the requested provider or model is not configured."""


def _get_env_value(role: str, field: str) -> str | None:
    env_key = f"{role}_{field}"
    value = os.getenv(env_key)
    return value.strip() if value else None


def _normalize_provider(provider: str | None) -> str:
    candidate = (provider or DEFAULT_PROVIDER).strip().lower()
    if candidate not in AVAILABLE_PROVIDERS:
        available = ", ".join(sorted(AVAILABLE_PROVIDERS))
        raise ConfigurationError(
            f"Unsupported provider '{provider}'. Available providers: {available}. "
            "Update src/config.py if you need to add more providers."
        )
    return candidate


def _resolve_model(provider_key: str, model: str | None) -> str:
    provider_cfg = AVAILABLE_PROVIDERS[provider_key]
    candidate = model or provider_cfg.default_model
    if candidate not in provider_cfg.models:
        allowed = ", ".join(provider_cfg.models)
        raise ConfigurationError(
            f"Unsupported model '{candidate}' for provider '{provider_cfg.identifier}'. "
            f"Allowed models: {allowed}. Update src/config.py if you need to add more models."
        )
    return candidate


def get_model_settings(
    role: str,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> Tuple[str, str]:
    """Resolve the provider/model pair for a given role (e.g., WHITE_AGENT or JUDGE)."""

    role_key = role.upper()
    provider_key = _normalize_provider(
        provider_override or _get_env_value(role_key, "PROVIDER")
    )
    model_name = _resolve_model(provider_key, model_override or _get_env_value(role_key, "MODEL"))
    provider_identifier = AVAILABLE_PROVIDERS[provider_key].identifier
    return provider_identifier, model_name


def describe_available_models() -> Dict[str, Tuple[str, ...]]:
    """Expose the configured providers and their models for reference."""

    return {cfg.identifier: cfg.models for cfg in AVAILABLE_PROVIDERS.values()}


__all__ = [
    "ConfigurationError",
    "describe_available_models",
    "get_model_settings",
    "AVAILABLE_PROVIDERS",
]


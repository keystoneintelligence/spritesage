"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (C) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from dataclasses import dataclass
from typing import Iterable

import openai
import google.genai as genai

PROVIDER_OPENAI = "OPENAI"
PROVIDER_GOOGLEAI = "GOOGLEAI"

CAPABILITY_TEXT = "text"
CAPABILITY_IMAGE = "image"

OPENAI_TEXT_MODEL_SETTING = "OPENAI_TEXT_MODEL"
OPENAI_IMAGE_MODEL_SETTING = "OPENAI_IMAGE_MODEL"
GOOGLE_TEXT_MODEL_SETTING = "GOOGLE_TEXT_MODEL"
GOOGLE_IMAGE_MODEL_SETTING = "GOOGLE_IMAGE_MODEL"

MODEL_SETTING_METADATA = {
    OPENAI_TEXT_MODEL_SETTING: (PROVIDER_OPENAI, CAPABILITY_TEXT),
    OPENAI_IMAGE_MODEL_SETTING: (PROVIDER_OPENAI, CAPABILITY_IMAGE),
    GOOGLE_TEXT_MODEL_SETTING: (PROVIDER_GOOGLEAI, CAPABILITY_TEXT),
    GOOGLE_IMAGE_MODEL_SETTING: (PROVIDER_GOOGLEAI, CAPABILITY_IMAGE),
}


@dataclass(frozen=True)
class ModelOption:
    provider: str
    model_id: str
    display_name: str
    capabilities: tuple[str, ...]
    description: str = ""
    source: str = "known"
    recommended: bool = False

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


_MODEL_CACHE = {
    PROVIDER_OPENAI: [],
    PROVIDER_GOOGLEAI: [],
}

NON_TEXT_MODEL_MARKERS = (
    "audio",
    "dall-e",
    "embed",
    "embedding",
    "image",
    "imagen",
    "moderation",
    "realtime",
    "search",
    "speech",
    "transcribe",
    "tts",
    "veo",
    "whisper",
)


def normalize_google_model_id(model_id: str) -> str:
    if not model_id:
        return ""
    if model_id.startswith("models/"):
        return model_id.split("/", 1)[1]
    if "/models/" in model_id:
        return model_id.rsplit("/models/", 1)[1]
    return model_id


def infer_model_capabilities(
    provider: str, model_id: str, supported_methods: Iterable[str] = ()
) -> tuple[str, ...]:
    model_id = normalize_google_model_id(model_id) if provider == PROVIDER_GOOGLEAI else model_id
    value = model_id.lower()
    supported = {method.lower() for method in supported_methods}
    capabilities = set()

    if provider == PROVIDER_OPENAI:
        if value.startswith("gpt-image") or value.startswith("dall-e"):
            capabilities.add(CAPABILITY_IMAGE)
        elif value.startswith(("gpt-", "o")) and not any(
            marker in value for marker in NON_TEXT_MODEL_MARKERS
        ):
            capabilities.add(CAPABILITY_TEXT)

    if provider == PROVIDER_GOOGLEAI:
        can_generate_content = not supported or "generatecontent" in supported
        if "image" in value or "imagen" in value:
            capabilities.add(CAPABILITY_IMAGE)
        elif (
            value.startswith("gemini-")
            and can_generate_content
            and not any(marker in value for marker in NON_TEXT_MODEL_MARKERS)
        ):
            capabilities.add(CAPABILITY_TEXT)

    return tuple(sorted(capabilities))


def set_cached_model_options(provider: str, options: Iterable[ModelOption]):
    _MODEL_CACHE[provider] = list(options)


def get_cached_model_options(provider: str) -> list[ModelOption]:
    return list(_MODEL_CACHE.get(provider, []))


def model_options_for_capability(
    provider: str,
    capability: str,
    options: Iterable[ModelOption] | None = None,
) -> list[ModelOption]:
    source_options = get_cached_model_options(provider) if options is None else list(options)
    return sorted(
        [
            option
            for option in source_options
            if option.provider == provider and option.supports(capability)
        ],
        key=lambda option: option.model_id,
    )


def discover_openai_model_options(api_key: str | None) -> list[ModelOption]:
    if not api_key:
        return []
    client = openai.OpenAI(api_key=api_key)
    response = client.models.list()
    options = []
    for model in getattr(response, "data", []):
        model_id = getattr(model, "id", "")
        capabilities = infer_model_capabilities(PROVIDER_OPENAI, model_id)
        if capabilities:
            options.append(
                ModelOption(
                    provider=PROVIDER_OPENAI,
                    model_id=model_id,
                    display_name=model_id,
                    capabilities=capabilities,
                    source="api",
                )
            )
    return options


def discover_google_model_options(api_key: str | None) -> list[ModelOption]:
    if not api_key:
        return []
    client = genai.Client(api_key=api_key)
    pager = client.models.list(config={"page_size": 200, "query_base": True})
    options = []
    for model in pager:
        raw_model_id = getattr(model, "base_model_id", None) or getattr(model, "name", "")
        model_id = normalize_google_model_id(raw_model_id)
        supported_methods = getattr(model, "supported_generation_methods", None) or []
        capabilities = infer_model_capabilities(PROVIDER_GOOGLEAI, model_id, supported_methods)
        if capabilities:
            options.append(
                ModelOption(
                    provider=PROVIDER_GOOGLEAI,
                    model_id=model_id,
                    display_name=getattr(model, "display_name", None) or model_id,
                    capabilities=capabilities,
                    description=getattr(model, "description", "") or "",
                    source="api",
                )
            )
    return options


def discover_model_options(provider: str, api_key: str | None) -> list[ModelOption]:
    if provider == PROVIDER_OPENAI:
        return discover_openai_model_options(api_key)
    if provider == PROVIDER_GOOGLEAI:
        return discover_google_model_options(api_key)
    return []


def refresh_model_cache(provider: str, api_key: str | None) -> list[ModelOption]:
    options = discover_model_options(provider, api_key)
    set_cached_model_options(provider, options)
    return options


def refresh_model_cache_for_settings(settings: dict) -> dict[str, Exception]:
    errors = {}
    provider_keys = {
        PROVIDER_OPENAI: "OPENAI_API_KEY",
        PROVIDER_GOOGLEAI: "GOOGLE_AI_STUDIO_API_KEY",
    }
    for provider, key in provider_keys.items():
        api_key = settings.get(key, "")
        if not api_key:
            continue
        try:
            refresh_model_cache(provider, api_key)
        except Exception as e:
            errors[provider] = e
            print(f"Warning: {provider} model discovery failed at startup: {e}")
    return errors

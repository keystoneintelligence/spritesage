"""Small, key-safe Image API adapter for OpenAI image generation and editing."""

from __future__ import annotations

import base64
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

import openai
from modelmanager.types import check_cancel, emit

_QUALITIES = {"low", "medium", "high"}


@dataclass(frozen=True)
class OpenAIImageConfig:
    model_id: str
    api_key: str = field(repr=False, compare=False)
    quality: str = "medium"

    def validate(self) -> None:
        if not self.model_id.startswith("gpt-image-"):
            raise ValueError(
                "The selected OpenAI image model does not support this editing workflow."
            )
        if self.quality not in _QUALITIES:
            raise ValueError("Choose low, medium, or high OpenAI image quality.")
        if not self.api_key.strip():
            raise ValueError("Set an OpenAI API key in Preferences before generating images.")

    def to_dict(self) -> dict[str, str]:
        """Saved jobs contain only public model settings, never credentials."""
        return {"provider": "OPENAI", "model_id": self.model_id, "quality": self.quality}

    @classmethod
    def from_dict(cls, data: dict, api_key: str) -> "OpenAIImageConfig":
        value = cls(str(data.get("model_id", "")), api_key, str(data.get("quality", "medium")))
        value.validate()
        return value


def generate_openai_image(
    config: OpenAIImageConfig,
    prompt: str,
    references: list[Path],
    progress: Callable | None = None,
    cancel=None,
) -> bytes:
    """Make exactly one billable request, without SDK retries or retained key state."""
    config.validate()
    if not prompt.strip():
        raise ValueError("Enter a description before generating an image.")
    check_cancel(cancel)
    # Automatic retries can duplicate billed image work after a lost response.
    client = openai.OpenAI(api_key=config.api_key, max_retries=0, timeout=240.0)
    emit(progress, f"Generating with OpenAI {config.model_id}…")
    with ExitStack() as stack:
        images = [stack.enter_context(Path(path).open("rb")) for path in references]
        if images:
            response = client.images.edit(
                model=config.model_id,
                prompt=prompt,
                image=cast(Any, images),
                n=1,
                size="1024x1024",
                quality=cast(Any, config.quality),
            )
        else:
            response = client.images.generate(
                model=config.model_id,
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality=cast(Any, config.quality),
            )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI returned no image data.")
    return base64.b64decode(response.data[0].b64_json, validate=True)

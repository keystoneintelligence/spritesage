"""Key-safe Gemini image generation for the selected Google image model."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from google import genai
from PIL import Image
from modelmanager.types import check_cancel, emit


@dataclass(frozen=True)
class GoogleImageConfig:
    model_id: str
    api_key: str = field(repr=False, compare=False)

    def validate(self) -> None:
        # Imagen models use a different API and cannot take two pose/identity images here.
        if not (self.model_id.startswith("gemini-") and "image" in self.model_id):
            raise ValueError(
                "The selected Google image model cannot edit two reference images. "
                "Choose a Gemini image model in Preferences."
            )
        if not self.api_key.strip():
            raise ValueError(
                "Set a Google AI Studio API key in Preferences before generating images."
            )

    def to_dict(self) -> dict[str, str]:
        return {"provider": "GOOGLEAI", "model_id": self.model_id}

    @classmethod
    def from_dict(cls, data: dict, api_key: str) -> "GoogleImageConfig":
        value = cls(str(data.get("model_id", "")), api_key)
        value.validate()
        return value


def generate_google_image(
    config: GoogleImageConfig,
    prompt: str,
    references: list[Path],
    progress: Callable | None = None,
    cancel=None,
) -> bytes:
    config.validate()
    if not prompt.strip():
        raise ValueError("Enter a description before generating an image.")
    check_cancel(cancel)
    emit(progress, f"Generating with Google {config.model_id}…")
    client = genai.Client(api_key=config.api_key)
    with ExitStack() as stack:
        images = [stack.enter_context(Image.open(path)) for path in references]
        response = client.models.generate_content(
            model=config.model_id,
            contents=[*images, prompt],
            config=genai.types.GenerateContentConfig(response_modalities=["Text", "Image"]),
        )
    for candidate in response.candidates or []:
        for part in getattr(getattr(candidate, "content", None), "parts", None) or []:
            data = getattr(part, "inline_data", None)
            if data is not None and str(getattr(data, "mime_type", "")).startswith("image/"):
                if data.data:
                    return data.data
    raise RuntimeError("Google returned no image data.")

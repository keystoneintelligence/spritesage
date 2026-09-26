"""Sprite Sage inputs adapted to the shared Model Manager image interface."""

from modelmanager import LocalConfig, ManagerError, ModelStore, get_profile
from modelmanager.generation import generate_image
from modelmanager.runtime import runtime_status

from .inference import (
    BaseAIClient,
    GoogleAIClient,
    MissingConfigurationException,
    OpenAIClient,
)


class LocalAIClient(BaseAIClient):
    def __init__(self, settings, progress=None, cancel=None):
        super().__init__("", "", None)
        self.settings = settings
        self.progress = progress
        self.cancel = cancel
        try:
            self.config = LocalConfig.from_dict(settings.get("LOCAL_GENERATION"))
        except ManagerError as error:
            raise MissingConfigurationException(
                f"Open Manage local models to correct the local setup: {error}"
            ) from error
        profile = get_profile(self.config.model_id)
        store = ModelStore(self.config.model_root, self.config.state_root)
        if runtime_status(self.config) != "Ready" or store.status(profile) != "Ready":
            raise MissingConfigurationException(
                "Set up Local image generation in LLM Settings → Manage local models."
            )

    def _text_client(self):
        provider = self.settings.get("LOCAL_TEXT_PROVIDER", "NONE")
        if provider == "OPENAI":
            key = self.settings.get("OPENAI_API_KEY")
            model = self.settings.get("OPENAI_TEXT_MODEL")
            if key and model:
                return OpenAIClient(api_key=key, text_model=model)
        elif provider == "GOOGLEAI":
            key = self.settings.get("GOOGLE_AI_STUDIO_API_KEY")
            model = self.settings.get("GOOGLE_TEXT_MODEL")
            if key and model:
                return GoogleAIClient(api_key=key, text_model=model)
        raise MissingConfigurationException(
            "Local currently generates images. Enter text manually, or choose an optional "
            "text-assistance provider in LLM Settings and configure its API key and text model."
        )

    def _image(self, input, references, purpose):
        constraints = []
        if purpose != "reference":
            constraints.extend(
                [
                    "Render one sprite animation frame, with a plain white background; keep the entire sprite visible and preserve the intended art style. Do not add scenery, text, borders, grids, or additional panels.",
                ]
            )
        camera = getattr(input, "camera", None)
        if isinstance(camera, str) and camera.strip().lower() not in {"", "none", "null"}:
            constraints.append(f"Preserve the requested camera perspective: {camera}.")
        if purpose == "next":
            constraints.append(
                "Use the supplied sprite as the preceding animation frame. Produce the next pose, preserving character identity, proportions, palette, scale, and framing."
            )
        elif purpose == "between":
            constraints.append(
                "Reference <image1> is the earlier animation frame and <image2> is the later frame. Produce exactly one midway pose between them, preserving their pixel art style, identity, proportions, scale, and framing."
            )
        elif purpose == "base" and references:
            constraints.append(
                "Use the references for the requested sprite's identity and art style; output a single base sprite, not a collage of the references."
            )
        return generate_image(
            self.config,
            input.to_prompt(),
            references,
            input.output_folder,
            progress=self.progress,
            cancel=self.cancel,
            constraints=tuple(constraints),
        )

    def generate_reference_image(self, input):
        return self._image(input, input.images or [], "reference")

    def generate_base_sprite_image(self, input):
        return self._image(input, input.images or [], "base")

    def generate_next_sprite_image(self, input):
        return self._image(input, [input.image], "next")

    def generate_sprite_between_images(self, input):
        return self._image(input, input.images, "between")

    def generate_description(self, input):
        return self._text_client().generate_description(input)

    def generate_keywords(self, input):
        return self._text_client().generate_keywords(input)

    def generate_sprite_animation_suggestion(self, input):
        return self._text_client().generate_sprite_animation_suggestion(input)


def check_local_setup():
    """Release diagnostic: exercise the installed engine from the frozen host."""
    from modelmanager.installation import verify_model
    from .settings import SettingsStore

    try:
        config = LocalConfig.from_dict(SettingsStore().load().get("LOCAL_GENERATION"))
        verify_model(config, lambda update: print(update.message, flush=True))
    except Exception as error:
        print(f"Local setup check failed: {error}", flush=True)
        return 1
    print("Local generation is ready.", flush=True)
    return 0


def test_local_generation(request_path):
    """Explicit release diagnostic using the same request adapters as the editor."""
    import json
    from pathlib import Path
    from . import inference
    from .settings import SettingsStore

    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        operations = {
            "base": (inference.GenerateBaseSpriteImageInput, "generate_base_sprite_image"),
            "reference": (inference.GenerateReferenceImageInput, "generate_reference_image"),
            "next": (inference.GenerateNextSpriteImageInput, "generate_next_sprite_image"),
            "between": (
                inference.GenerateSpriteBetweenImagesInput,
                "generate_sprite_between_images",
            ),
        }
        input_class, method = operations[request["operation"]]
        settings = (
            {"LOCAL_GENERATION": request["config"]}
            if "config" in request
            else SettingsStore().load()
        )
        client = LocalAIClient(settings, lambda update: print(update.message, flush=True))
        result = getattr(client, method)(input_class(**request["input"]))
        print(json.dumps({"output": result}), flush=True)
        return 0
    except Exception as error:
        print(f"Local generation test failed: {error}", flush=True)
        return 1

"""Offline contract checks for cloud image adapters; no network requests."""

import base64
from types import SimpleNamespace

import pytest
from PIL import Image

from spritesage import google_images, openai_images


def test_openai_25_generate_and_two_reference_edit_use_one_request_each(tmp_path, monkeypatch):
    pose = tmp_path / "pose.png"
    identity = tmp_path / "identity.png"
    Image.new("RGB", (8, 8), "red").save(pose)
    Image.new("RGB", (8, 8), "blue").save(identity)
    calls = []
    image_data = base64.b64encode(b"image bytes").decode()

    class Images:
        def generate(self, **kwargs):
            calls.append(("generate", kwargs))
            return SimpleNamespace(data=[SimpleNamespace(b64_json=image_data)])

        def edit(self, **kwargs):
            assert [item.name for item in kwargs["image"]] == [str(pose), str(identity)]
            calls.append(("edit", kwargs))
            return SimpleNamespace(data=[SimpleNamespace(b64_json=image_data)])

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {
                "api_key": "test-secret",
                "max_retries": 0,
                "timeout": 240.0,
            }
            self.images = Images()

    monkeypatch.setattr(openai_images.openai, "OpenAI", Client)
    config = openai_images.OpenAIImageConfig("gpt-image-2.5-flare", "test-secret")
    assert "test-secret" not in repr(config)
    assert "test-secret" not in str(config.to_dict())
    assert openai_images.generate_openai_image(config, "A green orc", []) == b"image bytes"
    assert (
        openai_images.generate_openai_image(config, "Copy pose", [pose, identity]) == b"image bytes"
    )
    assert [kind for kind, _ in calls] == ["generate", "edit"]
    for _, kwargs in calls:
        assert kwargs["model"] == "gpt-image-2.5-flare"
        assert kwargs["size"] == "1024x1024"
        assert kwargs["quality"] == "medium"
        assert kwargs["n"] == 1


def test_google_image_edit_passes_pose_then_identity_without_saving_key(tmp_path, monkeypatch):
    pose = tmp_path / "pose.png"
    identity = tmp_path / "identity.png"
    Image.new("RGB", (8, 8), "red").save(pose)
    Image.new("RGB", (8, 8), "blue").save(identity)
    calls = []

    class Models:
        def generate_content(self, **kwargs):
            images = kwargs["contents"][:2]
            assert [image.getpixel((0, 0)) for image in images] == [
                (255, 0, 0),
                (0, 0, 255),
            ]
            calls.append(kwargs)
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[
                                SimpleNamespace(
                                    inline_data=SimpleNamespace(
                                        mime_type="image/png", data=b"image bytes"
                                    )
                                )
                            ]
                        )
                    )
                ]
            )

    class Client:
        def __init__(self, api_key):
            assert api_key == "test-secret"
            self.models = Models()

    monkeypatch.setattr(google_images.genai, "Client", Client)
    config = google_images.GoogleImageConfig("gemini-3.1-flash-image", "test-secret")
    assert "test-secret" not in repr(config)
    assert "test-secret" not in str(config.to_dict())
    assert (
        google_images.generate_google_image(config, "Copy pose", [pose, identity]) == b"image bytes"
    )
    assert len(calls) == 1
    assert calls[0]["model"] == "gemini-3.1-flash-image"
    assert calls[0]["contents"][2] == "Copy pose"


@pytest.mark.parametrize(
    "config",
    [
        openai_images.OpenAIImageConfig("gpt-5.4", "test-secret"),
        google_images.GoogleImageConfig("imagen-4.0-generate-001", "test-secret"),
    ],
)
def test_non_edit_image_models_are_rejected_before_call(config):
    with pytest.raises(ValueError):
        config.validate()

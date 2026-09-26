"""Exercise context delivery at provider boundaries, not just prompt construction."""

import base64
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from spritesage import inference, local_inference, sprite_editor
from spritesage.art_context import ArtContext
from spritesage.config import APP_PALETTE
from spritesage.sage_file import SageFile
from spritesage.sprite_file import Animation, SpriteFile


@pytest.fixture
def art(tmp_path):
    paths = []
    for name, color in (
        ("before", "red"),
        ("after", "blue"),
        ("base", "green"),
        ("style", "yellow"),
    ):
        path = tmp_path / f"{name}.png"
        Image.new("RGB", (8, 8), color).save(path)
        paths.append(str(path))
    project = SageFile.from_dict(
        {
            "Project Description": "Moonlit watercolor world",
            "Keywords": "muted indigo",
            "Camera": "Isometric",
            "Reference Images": ["style.png"],
        },
        str(tmp_path / "world.sage"),
    )
    sprite = SpriteFile(
        "id", "Hero", "Fox with a copper scarf", 48, 64, paths[2], {}, pixel_art=False
    )
    return project, sprite, paths


def inputs(project, sprite, paths, operation):
    context = ArtContext.from_project(project, sprite)
    if operation == "base":
        return inference.GenerateBaseSpriteImageInput(
            project.directory,
            sprite.description,
            project.project_description,
            project.keywords,
            [],
            project.camera,
            context,
        ), [paths[2], paths[3]]
    if operation == "next":
        return inference.GenerateNextSpriteImageInput(
            project.directory,
            "walk",
            paths[0],
            project.camera,
            context,
        ), [paths[0], paths[2], paths[3]]
    return (
        inference.GenerateSpriteBetweenImagesInput(
            project.directory,
            "walk",
            paths[:2],
            project.camera,
            context,
        ),
        paths,
    )


@pytest.mark.parametrize("operation", ["base", "next", "between"])
@pytest.mark.parametrize("provider", ["openai", "google", "local"])
def test_all_providers_receive_complete_ordered_context(art, monkeypatch, operation, provider):
    project, sprite, paths = art
    item, expected = inputs(project, sprite, paths, operation)
    seen = []
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, "PNG")
    if provider == "openai":
        client = inference.OpenAIClient(image_model="test-image")

        def edit(**kwargs):
            seen.append((kwargs["prompt"], [handle.read() for handle in kwargs["image"]]))
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(output.getvalue()).decode())]
            )

        monkeypatch.setattr(inference.openai, "api_key", "test")
        monkeypatch.setattr(
            inference.openai.resources.images.Images, "edit", lambda self, **kwargs: edit(**kwargs)
        )
        monkeypatch.setattr(
            inference.openai.resources.images.Images,
            "generate",
            Mock(side_effect=AssertionError("references lost")),
        )
    elif provider == "google":
        client = inference.GoogleAIClient(api_key="test", image_model="test-image")

        def generate(**kwargs):
            seen.append(
                (
                    kwargs["contents"][-1],
                    [image.getpixel((0, 0)) for image in kwargs["contents"][:-1]],
                )
            )
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[
                                SimpleNamespace(
                                    inline_data=SimpleNamespace(
                                        data=output.getvalue(), mime_type="image/png"
                                    )
                                )
                            ]
                        )
                    )
                ]
            )

        monkeypatch.setattr(
            inference.genai,
            "Client",
            lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
        )
    else:
        monkeypatch.setattr(local_inference, "runtime_status", lambda config: "Ready")
        monkeypatch.setattr(local_inference.ModelStore, "status", lambda *args: "Ready")
        client = local_inference.LocalAIClient({})

        def generate(config, prompt, references, output_folder, **kwargs):
            seen.append((prompt, references))
            # The enhancement engine appends these constraints after rewriting.
            assert item.style_prompt() in kwargs["constraints"]
            return str(Path(output_folder) / "generated.png")

        monkeypatch.setattr(local_inference, "generate_image", generate)
    method = {
        "base": "generate_base_sprite_image",
        "next": "generate_next_sprite_image",
        "between": "generate_sprite_between_images",
    }[operation]
    assert getattr(client, method)(item)
    prompt, references = seen[0]
    for value in (
        project.project_description,
        project.keywords,
        project.camera,
        sprite.description,
        "48 x 64",
        "smooth artwork",
    ):
        assert value in prompt
    assert f"Image {len(expected)} (<image{len(expected)}>): project style" in prompt
    assert "converting it to pixel art" in prompt
    if provider == "openai":
        assert references == [Path(path).read_bytes() for path in expected]
    elif provider == "google":
        colors = []
        for path in expected:
            with Image.open(path) as image:
                colors.append(image.getpixel((0, 0)))
        assert references == colors
    else:
        assert references == expected


def test_reference_deduplication_preserves_two_identical_endpoints(art):
    project, sprite, paths = art
    context = replace(
        ArtContext.from_project(project, sprite), project_images=(paths[2], paths[3], paths[3])
    )
    item = inference.GenerateSpriteBetweenImagesInput(
        project.directory, "idle", [paths[2], paths[2]], project.camera, context
    )
    assert item.reference_paths() == [paths[2], paths[2], paths[3]]
    assert "Image 3 (<image3>): project style" in item.to_prompt()


@pytest.mark.parametrize("operation", ["base", "next", "between"])
def test_google_does_not_generate_when_a_style_reference_is_missing(art, monkeypatch, operation):
    project, sprite, paths = art
    item, _ = inputs(project, sprite, paths, operation)
    Path(paths[3]).unlink()
    generate = Mock(side_effect=AssertionError("must not send an incomplete request"))
    monkeypatch.setattr(
        inference.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
    )
    client = inference.GoogleAIClient(api_key="test")
    method = {
        "base": "generate_base_sprite_image",
        "next": "generate_next_sprite_image",
        "between": "generate_sprite_between_images",
    }[operation]
    assert getattr(client, method)(item) is None
    generate.assert_not_called()


@pytest.mark.parametrize(
    "action,index,frames",
    [
        ("before", 0, False),
        ("after", 0, False),
        ("before", 1, True),
        ("after", 0, True),
        ("base", 0, False),
    ],
)
def test_editor_actions_include_current_project_and_sprite_context(
    art, monkeypatch, action, index, frames
):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    assert app
    project, sprite, paths = art
    sprite.animations["walk"] = Animation("walk", paths[:2] if frames else [])
    view = sprite_editor.SpriteEditorView(APP_PALETTE)
    view.sage_file = project
    view.sprite_data = sprite
    view.desc_edit.setPlainText(sprite.description)
    view.anim_list_widget.addItem("walk")
    view.anim_list_widget.setCurrentRow(0)
    if frames:
        view.frame_list_widget.addItems(paths[:2])
        view.frame_list_widget.setCurrentRow(index)
    seen = []

    def capture(input):
        seen.append(input)
        return None

    manager = SimpleNamespace(
        generate_base_sprite_image=capture,
        generate_next_sprite_image=capture,
        generate_sprite_between_images=capture,
    )
    monkeypatch.setattr(sprite_editor, "AIModelManager", lambda: manager)
    monkeypatch.setattr(view, "_call_ai", lambda manager, fn, message: fn())
    if action == "base":
        view._on_base_image_action_clicked(0)
    else:
        getattr(view, f"_add_ai_generated_frame_{action}")()
    assert len(seen) == 1
    assert seen[0].art_context == ArtContext.from_project(project, sprite)
    assert paths[2] in seen[0].reference_paths() and paths[3] in seen[0].reference_paths()
    view.close()


@pytest.mark.parametrize("existing_sprite", [False, True])
def test_template_entry_points_forward_art_context(art, monkeypatch, existing_sprite):
    from PySide6.QtWidgets import QApplication, QDialog
    from spritesage import sage_editor
    from spritesage.animation_transfer import dialog

    app = QApplication.instance() or QApplication([])
    assert app
    project, sprite, _ = art
    view = (sprite_editor.SpriteEditorView if existing_sprite else sage_editor.SageEditorView)(
        APP_PALETTE
    )
    view.sage_file = project
    if existing_sprite:
        view.sprite_data = sprite
        view.current_file_path = str(Path(project.directory) / "hero.sprite")
        monkeypatch.setattr(view, "_get_sprite_data_to_save", lambda: sprite)
    seen = []

    class Dialog:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs["art_context"])

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(dialog, "AnimationTransferDialog", Dialog)
    view._animate_from_template()
    assert seen == [ArtContext.from_project(project, sprite if existing_sprite else None)]
    view.close()

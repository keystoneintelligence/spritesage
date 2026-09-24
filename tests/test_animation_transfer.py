from dataclasses import replace
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PIL import Image, ImageDraw
from modelmanager import Cancelled, LocalConfig

from spritesage.animation_transfer import catalog, service
from spritesage.model_baker.animations import AnimationClip
from spritesage.model_baker.vtk_baker import merge_bounds
from spritesage.sprite_file import Animation, SpriteFile


@pytest.fixture
def transfer(tmp_path, monkeypatch):
    model = tmp_path / "bandit.glb"
    model.write_bytes(b"test motion template")
    reference = tmp_path / "character.png"
    Image.new("RGB", (512, 512), cast(Any, "green")).save(reference)
    clips = [AnimationClip(0, "Walking", 1.05), AnimationClip(1, "Dead", 0.6)]
    monkeypatch.setattr(service, "inspect_animations", lambda path: clips)
    request = service.TransferRequest(
        tmp_path, model, reference, "Orc", "Green orc warrior", ("Walking",), max_frames=3
    )
    config = LocalConfig(
        str(tmp_path / "runtime"), str(tmp_path / "models"), str(tmp_path / "state"), seed=17
    )
    calls = []

    def fake_bake(config, **kwargs):
        assert config.lock_camera
        assert config.selected_views
        records = []
        for clip in clips:
            if clip.name not in config.selected_animations:
                continue
            times = service.frame_times(clip.duration, config.fps, config.max_frames)
            views = {}
            for direction in config.selected_views:
                frames = []
                for i, _ in enumerate(times):
                    kwargs["check_cancel"]()
                    path = config.output_dir / clip.name / direction / f"{i}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    image = Image.new("RGBA", (config.size, config.size))
                    ImageDraw.Draw(image).rectangle((100 + i * 10, 70, 320, 460), fill="brown")
                    image.save(path)
                    frames.append(str(path))
                views[direction] = frames
            records.append(
                {"name": clip.name, "duration": clip.duration, "times": times, "views": views}
            )
        config.output_dir.mkdir(exist_ok=True)
        (config.output_dir / "manifest.json").write_text(json.dumps({"animations": records}))

    def fake_generate(config, prompt, references, output_folder, progress, cancel):
        assert config.enhance_prompts is False
        assert config.seed == 17
        assert len(references) == 2
        assert all(Path(path).is_file() for path in references)
        calls.append((prompt, references))
        image = Image.new("RGB", (512, 512), cast(Any, "white"))
        ImageDraw.Draw(image).rectangle(
            (130, 80, 310 + len(calls), 450), fill=(40 + len(calls), 120, 60)
        )
        path = output_folder / f"generated-{len(calls)}.png"
        image.save(path)
        return str(path)

    monkeypatch.setattr(service, "bake", fake_bake)
    monkeypatch.setattr(service, "generate_image", fake_generate)
    return request, config, calls


def test_transfer_keeps_timing_directions_and_relative_manifest(transfer):
    request, config, calls = transfer
    request = replace(request, animations=("Walking", "Dead"), directions=("left", "right"))
    result = service.run_transfer(request, config)
    assert result.generated_frames == 12
    assert result.reused_frames == 0
    assert len(result.gif_paths) == 4
    assert len(result.sheet_paths) == 2
    walking = result.sprite.animations["Walking_left"]
    assert sum(walking.frame_seconds(i) for i in range(3)) == pytest.approx(1.05)
    assert result.sprite.animations["Dead_left"].loop is False
    assert result.sprite.include_base_image_in_animations is False
    manifest = json.loads(result.manifest_path.read_text())
    assert not Path(manifest["animations"][0]["views"]["left"][0]).is_absolute()
    with Image.open(result.gif_paths[0]) as gif:
        duration = 0
        for i in range(gif.n_frames):
            gif.seek(i)
            duration += gif.info["duration"]
        assert duration == 1050
        assert gif.info["loop"] == 0
    with Image.open(result.gif_paths[2]) as gif:
        assert "loop" not in gif.info
    assert len(calls) == 12


def test_cancellation_then_resume_reuses_only_verified_frames(transfer):
    request, config, calls = transfer
    cancel = Event()

    def stop_after_frame(update):
        if update.completed == 1:
            cancel.set()

    with pytest.raises(Cancelled):
        service.run_transfer(request, config, stop_after_frame, cancel)
    assert len(calls) == 1
    assert not list(request.project_dir.glob("sprites/*/manifest.json"))
    result = service.run_transfer(request, config)
    assert len(calls) == 3
    assert (result.generated_frames, result.reused_frames) == (2, 1)
    repeated = service.run_transfer(request, config)
    assert repeated.generated_frames == 0
    assert repeated.reused_frames == 3
    assert len(calls) == 3


def test_corrupt_prepared_frame_recovers_from_raw_without_generation(transfer):
    request, config, calls = transfer
    result = service.run_transfer(request, config)
    frame = Path(result.sprite.animations["Walking_right"].frames[1])
    frame.write_bytes(b"interrupted write")
    repeated = service.run_transfer(request, config)
    assert repeated.generated_frames == 0
    assert repeated.reused_frames == 2
    assert len(calls) == 3
    with Image.open(frame) as image:
        assert image.size == (128, 128)


def test_generation_failure_keeps_completed_work(transfer, monkeypatch):
    request, config, calls = transfer
    generate = service.generate_image

    def fail_second(*args, **kwargs):
        if calls:
            raise RuntimeError("engine unavailable")
        return generate(*args, **kwargs)

    monkeypatch.setattr(service, "generate_image", fail_second)
    with pytest.raises(RuntimeError, match="engine unavailable"):
        service.run_transfer(request, config)
    monkeypatch.setattr(service, "generate_image", generate)
    result = service.run_transfer(request, config)
    assert result.reused_frames == 1


def test_recipe_changes_do_not_reuse_wrong_character_or_settings(transfer):
    request, config, calls = transfer
    first = service.run_transfer(request, config)
    second = service.run_transfer(replace(request, description="Blue goblin"), config)
    assert first.output_dir != second.output_dir
    assert second.reused_frames == 0
    assert len(calls) == 6


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"animations": ()}, "animation"),
        ({"animations": ("Missing",)}, "animation"),
        ({"directions": ()}, "direction"),
        ({"directions": ("north",)}, "direction"),
        ({"animations": ("Walking", "Walking")}, "repeat"),
        ({"fps": float("nan")}, "Sampling"),
        ({"max_frames": 0}, "frames"),
        ({"zoom": 0}, "zoom"),
    ],
)
def test_invalid_requests_fail_before_expensive_generation(transfer, changes, message):
    request, config, calls = transfer
    with pytest.raises(ValueError, match=message):
        service.run_transfer(replace(request, **changes), config)
    assert calls == []


def test_output_stays_in_project_with_path_like_name(transfer):
    request, config, _ = transfer
    result = service.run_transfer(replace(request, sprite_name="../../orc"), config)
    assert result.output_dir.resolve().is_relative_to(request.project_dir)


def test_fixed_camera_bounds_cover_all_poses():
    first = merge_bounds(None, (0, 1, -1, 3, 2, 5))
    assert merge_bounds(first, (-2, 0.5, 0, 4, -1, 4)) == (-2, 1, -1, 4, -1, 5)


def test_pose_prompt_uses_qwen_reference_tags_and_does_not_confuse_camera_with_facing():
    prompt = service.transfer_prompt("Green orc", "Walking", "right", 0, 6)
    assert "<image1> is the canvas" in prompt
    assert "<image2> supplies ONLY" in prompt
    assert "image 1" not in prompt
    # A camera on the model's right side can show a character facing left on screen.
    assert "right" not in prompt


def test_background_cleanup_keeps_enclosed_white_details():
    image = Image.new("RGB", (32, 32), cast(Any, "white"))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 24, 24), fill="green")
    draw.rectangle((13, 13, 16, 16), fill="white")
    clean = service.remove_white_background(image)
    assert clean.getpixel((0, 0))[3] == 0
    assert clean.getpixel((14, 14))[3] == 255
    assert clean.getchannel("A").getbbox() == (8, 8, 25, 25)


def test_merge_preserves_existing_animations_and_fits_canvas(transfer):
    request, config, _ = transfer
    result = service.run_transfer(request, config)
    existing = Animation("Walking_right", [str(request.reference_image)])
    sprite = SpriteFile(
        "old-id",
        "Old",
        "description",
        64,
        96,
        str(request.reference_image),
        {"Walking_right": existing},
    )
    service.merge_animations(sprite, result)
    assert sprite.animations["Walking_right"] is existing
    assert sprite.include_base_image_in_animations is True
    added = sprite.animations["Walking_right_2"]
    assert added.name == "Walking_right_2"
    assert added.frame_durations == result.sprite.animations["Walking_right"].frame_durations
    with Image.open(added.frames[0]) as frame:
        assert frame.size == (64, 96)


def test_template_catalog_registers_external_model_without_copying(transfer, monkeypatch):
    request, _, _ = transfer
    monkeypatch.setattr(catalog, "inspect_animations", lambda p: [AnimationClip(0, "Walking", 1)])
    library = catalog.TemplateLibrary(request.project_dir / "catalog.json")
    entry = library.register(request.model_path, name="Bandit")
    assert entry.character_type == "Humanoid"
    assert entry.model_path == str(request.model_path.resolve())
    assert library.load() == [entry]
    moved = request.project_dir / "moved.glb"
    moved.write_bytes(request.model_path.read_bytes())
    updated = library.register(moved, name="Bandit moved")
    assert library.load() == [updated]
    assert updated.id == entry.id


def test_no_animation_model_cannot_be_a_template(transfer, monkeypatch):
    request, _, _ = transfer
    monkeypatch.setattr(catalog, "inspect_animations", lambda p: [])
    with pytest.raises(ValueError, match="no animation"):
        catalog.TemplateLibrary(request.project_dir / "catalog.json").register(request.model_path)


def test_dialog_default_flow_and_advanced_settings(transfer, monkeypatch):
    from PySide6 import QtWidgets, QtCore
    from spritesage.animation_transfer import dialog
    from spritesage.config import APP_PALETTE

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app
    request, config, _ = transfer
    monkeypatch.setattr(
        catalog,
        "inspect_animations",
        lambda p: [AnimationClip(0, "Walking", 1), AnimationClip(1, "Running", 0.5)],
    )
    monkeypatch.setattr(dialog, "inspect_animations", catalog.inspect_animations)
    monkeypatch.setattr(dialog, "runtime_status", lambda c: "Ready")
    monkeypatch.setattr(dialog.ModelStore, "status", lambda *a: "Ready")
    library = catalog.TemplateLibrary(request.project_dir / "catalog.json")
    settings = SimpleNamespace(load=lambda: {"LOCAL_GENERATION": config.to_dict()})
    window = dialog.AnimationTransferDialog(
        request.project_dir, APP_PALETTE, library=library, settings_store=settings
    )
    assert window.type_combo.currentText() == "Humanoid"
    assert window.animation_list.count() == 0
    assert not window.generate_button.isEnabled()
    assert window.advanced_widget.isHidden()
    entry = library.register(request.model_path)
    window._load_templates(entry.id)
    window.name_edit.setText("Orc")
    window.description_edit.setPlainText("Green orc")
    window._set_reference(request.reference_image)
    assert window._selected_animations() == ("Walking",)
    assert window._directions() == ("right",)
    assert window.generate_button.isEnabled()
    assert window.to_request().max_frames == 8
    window.animation_list.item(1).setCheckState(QtCore.Qt.CheckState.Checked)
    assert len(window.to_request().animations) == 2
    window.advanced_toggle.setChecked(True)
    assert not window.advanced_widget.isHidden()
    result = service.run_transfer(request, config)
    state_path = result.output_dir / "progress.json"
    state = json.loads(state_path.read_text())
    state["complete"] = False
    state_path.write_text(json.dumps(state))
    window._refresh_saved_jobs()
    assert len(window.saved_jobs) == 1
    window.description_edit.setPlainText("Different character")
    window.restore_request(result.output_dir / "request.json")
    assert window.to_request() == request
    assert window.local_config == config.to_dict()
    window.close()


def test_editor_creation_and_undoable_animation_merge(transfer, monkeypatch):
    from PySide6 import QtWidgets
    from spritesage.animation_transfer import dialog
    from spritesage.config import APP_PALETTE
    from spritesage.sage_editor import SageEditorView
    from spritesage.sage_file import SageFile
    from spritesage.sprite_editor import SpriteEditorView

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app
    request, config, _ = transfer
    result = service.run_transfer(request, config)

    class CompletedDialog:
        def __init__(self, *args, **kwargs):
            self.result_data = result

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialog, "AnimationTransferDialog", CompletedDialog)
    project = SageFile(
        "Test",
        "1",
        "",
        "Fantasy sprites",
        "pixel art",
        "",
        [],
        "",
        str(request.project_dir / "test.sage"),
    )
    view = SageEditorView(APP_PALETTE)
    view.sage_file = project
    monkeypatch.setattr(view, "_refresh_sprite_table", lambda: None)
    opened = []
    view.sprite_row_action.connect(opened.append)
    view._animate_from_template()
    sprite_path = request.project_dir / "Orc.sprite"
    assert opened == [str(sprite_path)]
    assert (
        SpriteFile.from_json(str(sprite_path), str(request.project_dir))
        .animations["Walking_right"]
        .loop
    )

    editor = SpriteEditorView(APP_PALETTE)
    editor.load_sprite_data(str(sprite_path), project)
    editor._animate_from_template()
    assert set(editor.sprite_data.animations) == {"Walking_right", "Walking_right_2"}
    editor.undo()
    saved = SpriteFile.from_json(str(sprite_path), str(request.project_dir))
    assert set(saved.animations) == {"Walking_right"}
    editor.close()
    view.close()

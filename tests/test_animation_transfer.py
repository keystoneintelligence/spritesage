from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PIL import Image, ImageDraw
from modelmanager import Cancelled, LocalConfig

from spritesage.animation_transfer import catalog, service
from spritesage.google_images import GoogleImageConfig
from spritesage.openai_images import OpenAIImageConfig
from spritesage.animation_transfer.pose_guidance import rig_constraints
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
        assert config.seed >= 17
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


@pytest.mark.parametrize("provider", ["OPENAI", "GOOGLEAI"])
def test_cloud_transfer_uses_selected_image_model_without_saving_key(
    transfer, monkeypatch, provider
):
    request, _, _ = transfer
    request = replace(request, generation_size=1024 if provider == "OPENAI" else 512)
    key = "private-test-key-never-save"
    config = (
        OpenAIImageConfig("gpt-image-2.5-sunburst", key)
        if provider == "OPENAI"
        else GoogleImageConfig("gemini-3.1-flash-image", key)
    )
    settings = {
        "Selected Inference Provider": provider,
        "OPENAI_IMAGE_MODEL": "gpt-image-2.5-sunburst",
        "OPENAI_API_KEY": key,
        "GOOGLE_IMAGE_MODEL": "gemini-3.1-flash-image",
        "GOOGLE_AI_STUDIO_API_KEY": key,
    }
    assert service.config_from_settings(settings).to_dict() == config.to_dict()
    cloud_calls = []

    def fake_cloud_generate(selected, prompt, references, progress, cancel):
        assert selected.model_id == config.model_id
        assert len(references) == 2
        assert all(path.is_file() for path in references)
        assert "first image" in prompt and "second image" in prompt
        cloud_calls.append(prompt)
        output = BytesIO()
        Image.new("RGB", (request.generation_size,) * 2, "green").save(output, "PNG")
        return output.getvalue()

    adapter = "generate_openai_image" if provider == "OPENAI" else "generate_google_image"
    monkeypatch.setattr(service, adapter, fake_cloud_generate)
    result = service.run_transfer(request, config)
    assert result.generated_frames == 3
    assert len(cloud_calls) == 3
    assert key not in (result.output_dir / "request.json").read_text()
    assert key not in (result.output_dir / "recipe.json").read_text()
    assert key not in (result.output_dir / "progress.json").read_text()
    assert service.run_transfer(request, config).generated_frames == 0
    assert len(cloud_calls) == 3


def test_cloud_retry_requires_same_global_model_before_another_request(transfer, monkeypatch):
    request, _, _ = transfer
    request = replace(request, generation_size=1024)
    config = OpenAIImageConfig("gpt-image-2.5-flare", "private-test-key-never-save")
    calls = []

    def fake_generate(*args):
        calls.append(args)
        output = BytesIO()
        Image.new("RGB", (1024, 1024), "green").save(output, "PNG")
        return output.getvalue()

    monkeypatch.setattr(service, "generate_openai_image", fake_generate)
    result = service.run_transfer(request, config)
    from spritesage import settings as settings_module

    current = {
        "Selected Inference Provider": "OPENAI",
        "OPENAI_IMAGE_MODEL": "gpt-image-2.5-sunburst",
        "OPENAI_API_KEY": "private-test-key-never-save",
    }
    monkeypatch.setattr(
        settings_module, "SettingsStore", lambda: SimpleNamespace(load=lambda: current)
    )
    with pytest.raises(Exception, match="different image provider or model"):
        service.retry_transfer_frame(result, "Walking", "right", 0)
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


def test_pose_guidance_uses_rig_facts_and_rejects_conflicting_boot_caption(transfer, monkeypatch):
    request, config, calls = transfer

    class Guide:
        def __init__(self, *args):
            pass

        def constraints(self, *args):
            return ("The screen-right boot is higher than the screen-left boot.",)

    class Helper:
        def __init__(self, *args):
            pass

        def rewrite(self, *args, **kwargs):
            return (
                "Edit <image1> using <image2>. The screen-left boot is lifted. "
                "The screen-right boot is planted."
            )

    monkeypatch.setattr(service, "enhancement_status", lambda *args: "Ready")
    monkeypatch.setattr(service, "RigPoseGuide", Guide)
    monkeypatch.setattr(service, "PromptEngine", Helper)
    result = service.run_transfer(replace(request, pose_guided=True), config)
    assert result.generated_frames == 3
    assert len(calls) == 3
    assert "screen-right boot is higher" in calls[0][0]
    assert "screen-left boot is lifted" not in calls[0][0]
    assert json.loads(result.manifest_path.read_text())["pose_guided"] is True


def test_rig_constraints_map_common_humanoid_joints_and_skip_unknown_skeletons():
    points = {
        "mixamorig:Head": (230, 100),
        "headfront": (210, 100),
        "mixamorig:LeftFoot": (165, 400),
        "mixamorig:RightFoot": (330, 365),
        "mixamorig:LeftHand": (190, 250),
        "mixamorig:RightHand": (300, 260),
    }
    facts = " ".join(rig_constraints(points, 512))
    assert "screen left" in facts
    assert "screen-right boot is higher" in facts
    assert "boot centers" in facts
    assert "hand centers" in facts
    assert rig_constraints({"unnamed_joint": (4, 5)}, 512) == ()


def test_boot_guard_accepts_correct_two_boot_clause_and_rejects_swapped_contact():
    facts = ("The screen-right boot is higher than the screen-left boot.",)
    assert not service._contradicts_boot_height(
        "The screen-left boot is planted, while the screen-right boot is lifted.", facts
    )
    assert service._contradicts_boot_height(
        "The screen-left boot is lifted, while the screen-right boot is planted.", facts
    )


def test_retry_preserves_versions_and_rebuilds_animation_preview(transfer):
    request, config, calls = transfer
    result = service.run_transfer(request, config)
    frame = Path(result.sprite.animations["Walking_right"].frames[1])
    first = frame.read_bytes()
    before_gif = result.gif_paths[0].read_bytes()
    assert service.frame_attempts(result, "Walking", "right", 1) == (1, 0)

    service.retry_transfer_frame(result, "Walking", "right", 1, "Keep the boot raised")
    second = frame.read_bytes()
    assert second != first
    assert result.gif_paths[0].read_bytes() != before_gif
    assert service.frame_attempts(result, "Walking", "right", 1) == (2, 1)
    assert len(calls) == 4

    service.select_frame_attempt(result, "Walking", "right", 1, 0)
    assert frame.read_bytes() == first
    service.select_frame_attempt(result, "Walking", "right", 1, 1)
    assert frame.read_bytes() == second
    service.accept_transfer(result)
    assert json.loads((result.output_dir / "progress.json").read_text())["accepted"] is True


def test_failed_retry_keeps_current_draft(transfer, monkeypatch):
    request, config, _ = transfer
    result = service.run_transfer(request, config)
    frame = Path(result.sprite.animations["Walking_right"].frames[0])
    first = frame.read_bytes()
    monkeypatch.setattr(
        service, "generate_image", lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    with pytest.raises(RuntimeError, match="offline"):
        service.retry_transfer_frame(result, "Walking", "right", 0)
    assert frame.read_bytes() == first
    assert service.frame_attempts(result, "Walking", "right", 0) == (1, 0)


def test_frame_review_shows_pose_and_output_and_retries_selected_frame(transfer, monkeypatch):
    from PySide6 import QtWidgets
    from spritesage.animation_transfer import review
    from spritesage.config import APP_PALETTE

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app
    request, config, calls = transfer
    result = service.run_transfer(request, config)
    monkeypatch.setattr(review, "run_task", lambda parent, title, task, palette: task(None, None))
    window = review.FrameReviewDialog(result, APP_PALETTE)
    assert window.frame_list.count() == 3
    assert not window.expected_label.pixmap().isNull()
    assert not window.output_label.pixmap().isNull()
    window.frame_list.setCurrentRow(1)
    window.feedback_edit.setText("Lift the back boot")
    window.retry_button.click()
    assert len(calls) == 4
    assert window.version_combo.count() == 2
    window.version_combo.setCurrentIndex(0)
    assert service.frame_attempts(result, "Walking", "right", 1) == (2, 0)
    window._accept()
    assert window.result() == QtWidgets.QDialog.DialogCode.Accepted
    window.close()


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
    bundled = library.load()[0]
    entry = library.register(request.model_path, name="Bandit")
    assert entry.character_type == "Humanoid"
    assert entry.model_path == str(request.model_path.resolve())
    assert library.load() == [bundled, entry]
    moved = request.project_dir / "moved.glb"
    moved.write_bytes(request.model_path.read_bytes())
    updated = library.register(moved, name="Bandit moved")
    assert library.load() == [bundled, updated]
    assert updated.id == entry.id
    saved = json.loads(library.path.read_text(encoding="utf-8"))
    assert len(saved["templates"]) == 1
    assert saved["templates"][0]["model_path"] == str(moved.resolve())


def test_bundled_bandit_is_stable_and_usable_in_packaged_app(tmp_path, monkeypatch):
    import shutil

    source = catalog.bundled_bandit_path()
    bundle = tmp_path / "bundle" / "motion_templates"
    bundle.mkdir(parents=True)
    shutil.copyfile(source, bundle / "bandit.glb")
    monkeypatch.setattr(catalog, "bundled_bandit_path", lambda: bundle / "bandit.glb")
    library = catalog.TemplateLibrary(tmp_path / "app-data" / "catalog.json")
    (bandit,) = library.load()
    assert bandit.name == "Bandit"
    assert bandit.character_type == "Humanoid"
    assert Path(bandit.model_path).parent == library.path.parent / "motion-templates"
    assert Path(bandit.model_path).read_bytes() == source.read_bytes()
    assert {clip.name for clip in catalog.inspect_animations(bandit.model_path)} == {
        "Walking",
        "Running",
        "Run_03",
        "Dead",
    }
    assert not library.path.exists()
    assert library.load() == [bandit]
    Path(bandit.model_path).write_bytes(b"damaged")
    assert library.load() == [bandit]
    assert Path(bandit.model_path).read_bytes() == source.read_bytes()


def test_first_run_dialog_offers_bundled_bandit(transfer, monkeypatch):
    from PySide6 import QtWidgets

    from spritesage.animation_transfer import dialog
    from spritesage.config import APP_PALETTE

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app
    request, config, _ = transfer
    monkeypatch.setattr(dialog, "runtime_status", lambda c: "Ready")
    monkeypatch.setattr(dialog.ModelStore, "status", lambda *a: "Ready")
    monkeypatch.setattr(dialog, "enhancement_status", lambda *a: "Ready")
    library = catalog.TemplateLibrary(request.project_dir / "catalog.json")
    settings = SimpleNamespace(
        load=lambda: {
            "Selected Inference Provider": "LOCAL",
            "LOCAL_GENERATION": config.to_dict(),
        }
    )
    window = dialog.AnimationTransferDialog(
        request.project_dir, APP_PALETTE, library=library, settings_store=settings
    )
    assert window.type_combo.currentText() == "Humanoid"
    assert window.template_combo.currentText() == "Bandit"
    assert {clip.name for clip in window.clips} == {"Walking", "Running", "Run_03", "Dead"}
    assert window._selected_animations() == ("Walking",)
    window.close()


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
    monkeypatch.setattr(dialog, "enhancement_status", lambda *a: "Ready")
    monkeypatch.setattr(catalog, "bundled_bandit_path", lambda: request.project_dir / "missing.glb")
    library = catalog.TemplateLibrary(request.project_dir / "catalog.json")
    settings = SimpleNamespace(
        load=lambda: {
            "Selected Inference Provider": "LOCAL",
            "LOCAL_GENERATION": config.to_dict(),
        }
    )
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
    assert window.to_request().pose_guided is True
    assert window.to_request().max_frames == 8
    window.animation_list.item(1).setCheckState(QtCore.Qt.CheckState.Checked)
    assert len(window.to_request().animations) == 2
    window.advanced_toggle.setChecked(True)
    assert not window.advanced_widget.isHidden()
    result = service.run_transfer(request, config)
    window._refresh_saved_jobs()
    assert any("ready to review" in label for label, _ in window.saved_jobs)
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


def test_dialog_transfer_uses_global_openai_selection(transfer, monkeypatch):
    from PySide6 import QtWidgets
    from spritesage.animation_transfer import dialog
    from spritesage.config import APP_PALETTE

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app
    request, _, _ = transfer
    monkeypatch.setattr(
        catalog, "inspect_animations", lambda path: [AnimationClip(0, "Walking", 1)]
    )
    monkeypatch.setattr(dialog, "inspect_animations", catalog.inspect_animations)
    library = catalog.TemplateLibrary(request.project_dir / "catalog.json")
    entry = library.register(request.model_path)
    settings = SimpleNamespace(
        load=lambda: {
            "Selected Inference Provider": "OPENAI",
            "OPENAI_IMAGE_MODEL": "gpt-image-2.5-flare",
            "OPENAI_API_KEY": "private-test-key-never-save",
        }
    )
    window = dialog.AnimationTransferDialog(
        request.project_dir, APP_PALETTE, library=library, settings_store=settings
    )
    window._load_templates(entry.id)
    window.name_edit.setText("Orc")
    window.description_edit.setPlainText("Green orc")
    window._set_reference(request.reference_image)
    assert window.generate_button.isEnabled()
    assert not window.resolution_combo.isEnabled()
    assert window.resolution_combo.currentData() == 1024
    assert not window.manage_button.isVisible()
    assert "billable OpenAI" in window.estimate_label.text()
    selected = []
    monkeypatch.setattr(window, "_confirm_cloud_generation", lambda model, count: False)
    monkeypatch.setattr(dialog, "run_task", lambda parent, title, task, palette: task(None, None))
    monkeypatch.setattr(
        dialog,
        "run_transfer",
        lambda req, config, progress, cancel: selected.append((req, config)),
    )
    window._generate()
    assert selected == []
    monkeypatch.setattr(window, "_confirm_cloud_generation", lambda model, count: True)
    window._generate()
    assert len(selected) == 1
    assert selected[0][1].model_id == "gpt-image-2.5-flare"
    assert selected[0][0].generation_size == 1024
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
    assert json.loads((result.output_dir / "progress.json").read_text())["accepted"] is True
    assert (
        SpriteFile.from_json(str(sprite_path), str(request.project_dir))
        .animations["Walking_right"]
        .loop
    )

    editor = SpriteEditorView(APP_PALETTE)
    editor.load_sprite_data(str(sprite_path), project)
    editor._animate_from_template()
    assert editor.sprite_data is not None
    assert set(editor.sprite_data.animations) == {"Walking_right", "Walking_right_2"}
    editor.undo()
    saved = SpriteFile.from_json(str(sprite_path), str(request.project_dir))
    assert set(saved.animations) == {"Walking_right"}
    editor.close()
    view.close()


def test_failed_project_save_keeps_animation_draft_for_review(transfer, monkeypatch):
    from PySide6 import QtWidgets
    from spritesage.animation_transfer import dialog
    from spritesage.config import APP_PALETTE
    from spritesage.sage_editor import SageEditorView
    from spritesage.sage_file import SageFile

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
    monkeypatch.setattr(
        result.sprite,
        "save",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")),
    )
    warnings = []
    monkeypatch.setattr(
        "spritesage.sage_editor.QMessageBox.warning",
        lambda *args: warnings.append(args[2]),
    )
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
    view._animate_from_template()
    assert warnings == ["disk full"]
    assert not json.loads((result.output_dir / "progress.json").read_text()).get("accepted")
    view.close()

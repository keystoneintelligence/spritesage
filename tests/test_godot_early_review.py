"""Review user changes before invoking any background-removal work."""

import pytest
from PIL import Image

from spritesage.exporter import GodotProjectExporter
from tests.test_godot_preservation import asset as asset, files, replace_frame
from tests.test_export_ui import DummyExportWidget, qapp as qapp


@pytest.mark.parametrize("accept", [False, True])
def test_review_precedes_cleanup_and_cancel_never_processes(asset, monkeypatch, tmp_path, accept):
    from spritesage import spritesheet

    sprite, exporter = asset
    # An opaque replacement really requires the existing cleanup pipeline.
    Image.new("RGB", (8, 8), "white").save(sprite.animations["attack"].frames[2])
    before = files(exporter.output_dir)
    events = []

    def cleanup(images):
        assert events == ["review"]
        events.append("cleanup")
        cleaned = []
        for image in images:
            result = Image.new("RGBA", image.size)
            result.putpixel((1, 1), (255, 0, 0, 128))
            cleaned.append(result)
        return cleaned

    monkeypatch.setattr(spritesheet, "remove_background_images", cleanup)
    widget = DummyExportWidget(str(tmp_path))

    def confirm(plan):
        events.append("review")
        assert files(exporter.output_dir) == before
        assert any("frame 3" in value.lower() for value in plan.updates)
        return accept

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    assert events == (["review", "cleanup"] if accept else ["review"])
    if accept:
        with Image.open(exporter.output_dir / "Hero_sheet.png") as sheet:
            assert sheet.getpixel((23, 7))[3] == 0  # Opaque source must be cleaned.
    else:
        assert files(exporter.output_dir) == before


@pytest.mark.parametrize("edit", ["add", "remove", "timing", "art"])
def test_review_is_read_only_and_describes_animation_edits(asset, monkeypatch, edit):
    from spritesage import spritesheet

    sprite, exporter = asset

    def forbidden(*args, **kwargs):
        raise AssertionError("Review must not invoke the production rendering pipeline")

    monkeypatch.setattr(spritesheet.SpriteSheetGenerator, "render_frames", forbidden)
    if edit == "add":
        sprite.animations["attack"].frames.append(sprite.animations["idle"].frames[0])
        sprite.animations["attack"].frame_durations.append(1)
    elif edit == "remove":
        sprite.animations["attack"].select_frames([0, 1, 3, 4, 5])
    elif edit == "timing":
        sprite.animations["attack"].frame_durations[2] = 3
    else:
        replace_frame(sprite)
    before = files(exporter.output_dir)
    review = exporter.review()
    assert files(exporter.output_dir) == before
    from spritesage.godot_export_review import friendly_changes

    summary = "\n".join(friendly_changes(review.updates)).lower()
    expected = {
        "add": "added",
        "remove": "removed",
        "timing": "changed timing",
        "art": "changed artwork",
    }
    assert expected[edit] in summary
    assert "pixel region" not in summary
    assert "rect2" not in summary
    with pytest.raises(ValueError, match="review"):
        review.apply(allow_conflicts=True)
    assert files(exporter.output_dir) == before


def test_source_change_after_review_stops_before_cleanup(asset, monkeypatch, tmp_path):
    from spritesage import spritesheet

    sprite, exporter = asset
    replace_frame(sprite)
    before = files(exporter.output_dir)
    widget = DummyExportWidget(str(tmp_path))

    def confirm(plan):
        Image.new("RGB", (8, 8), "white").save(sprite.animations["attack"].frames[2])
        return True

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    monkeypatch.setattr(
        spritesheet,
        "remove_background_images",
        lambda *args: pytest.fail("stale review ran cleanup"),
    )
    with pytest.raises(ValueError, match="changed"):
        widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    assert files(exporter.output_dir) == before


def test_project_reviews_all_sprites_without_cleanup(asset, tmp_path, monkeypatch):
    from spritesage import spritesheet

    sprite, exporter = asset
    project = tmp_path / "source"
    project.mkdir()
    sprite.save(str(project / "hero.sprite"), str(project))
    output = tmp_path / "project-export"
    project_exporter = GodotProjectExporter(str(project), str(output))
    project_exporter.export()
    replace_frame(sprite)
    monkeypatch.setattr(
        spritesheet,
        "remove_background_images",
        lambda *args: pytest.fail("project review ran cleanup"),
    )
    before = files(output)
    review = project_exporter.review()
    assert review.updates
    assert files(output) == before


def test_png_diff_uses_artwork_language_not_pixel_coordinates(tmp_path):
    from spritesage.godot_export_diff import review_candidates
    from spritesage.godot_export_transaction import ExportPlan

    path = tmp_path / "Hero_sheet.png"
    Image.new("RGBA", (8, 8)).save(path)
    before = path.read_bytes()
    image = Image.new("RGBA", (8, 8))
    image.putpixel((7, 7), (255, 0, 0, 128))
    image.save(path)
    candidate = path.read_bytes()
    path.write_bytes(before)
    plan = review_candidates(
        ExportPlan(root=tmp_path, writes={path: candidate}, guards={path: before})
    )
    summary = "\n".join(plan.file_summaries[path])
    assert "artwork" in summary.lower()
    assert "pixel region" not in summary
    assert "(7, 7" not in summary


def test_background_cleanup_cannot_hide_an_explicit_art_change(asset, monkeypatch, tmp_path):
    # Review the art operation even if the unprocessed replacement happens to
    # equal current Godot pixels. Processing is allowed to change transparency.
    sprite, exporter = asset
    replace_frame(sprite)
    with Image.open(exporter.output_dir / "Hero_sheet.png") as current:
        cell = current.crop((16, 0, 24, 8))
    cell.save(sprite.animations["attack"].frames[2])
    # Ensure this is a distinct source frame from the baseline (the crop includes
    # the originally rendered cell and a source-only extra mark).
    cell.putpixel((7, 7), (255, 0, 0, 128))
    cell.save(sprite.animations["attack"].frames[2])
    with Image.open(exporter.output_dir / "Hero_sheet.png") as current:
        sheet = current.convert("RGBA")
    sheet.paste(cell, (16, 0))
    sheet.save(exporter.output_dir / "Hero_sheet.png")
    widget = DummyExportWidget(str(tmp_path))
    reviewed = []
    monkeypatch.setattr(
        widget, "_confirm_godot_export", lambda plan: reviewed.append(plan.updates) or False
    )
    widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    assert reviewed and any("frame 3" in change for change in reviewed[0])


def test_native_dialog_uses_animation_language_without_coordinates(asset, monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    from PySide6.QtCore import QTimer

    sprite, exporter = asset
    replace_frame(sprite)
    sprite.animations["attack"].frame_durations[2] = 3
    before = files(exporter.output_dir)
    widget = DummyExportWidget(str(tmp_path))
    captured = []

    def cancel():
        box = QtWidgets.QApplication.activeModalWidget()
        if isinstance(box, QtWidgets.QMessageBox):
            captured.append(box.informativeText())
            assert "Changed artwork for animation frame 3" in box.informativeText()
            assert "Changed timing" in box.informativeText()
            assert "pixel region" not in box.informativeText()
            assert "AtlasTexture" not in box.informativeText()
            box.button(QtWidgets.QMessageBox.StandardButton.Cancel).click()

    timer = QTimer()
    timer.timeout.connect(cancel)
    timer.start(10)
    try:
        widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    finally:
        timer.stop()
        widget.close()
    assert len(captured) == 1
    assert files(exporter.output_dir) == before


@pytest.mark.parametrize("accept", [False, True])
def test_static_sprite_cleanup_runs_only_after_review(tmp_path, monkeypatch, accept):
    from spritesage import exporter as module
    from spritesage.sprite_file import SpriteFile

    image = tmp_path / "static.png"
    Image.new("RGB", (8, 8), "white").save(image)
    sprite = SpriteFile("static", "Static", "", 8, 8, str(image), {})
    monkeypatch.setattr(
        module, "remove_background_image", lambda image: Image.new("RGBA", image.size)
    )
    output = tmp_path / "export"
    module.GodotSpriteExporter(sprite, str(output)).export()
    Image.new("RGB", (8, 8), "red").save(image)
    before = files(output)
    events = []

    def cleanup(image):
        assert events == ["review"]
        events.append("cleanup")
        return Image.new("RGBA", image.size)

    monkeypatch.setattr(module, "remove_background_image", cleanup)
    widget = DummyExportWidget(str(tmp_path))

    def confirm(plan):
        events.append("review")
        return accept

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    widget._run_godot_export(
        module.GodotSpriteExporter(sprite, str(output)), lambda parent, fn, **kwargs: fn()
    )
    assert events == (["review", "cleanup"] if accept else ["review"])
    if not accept:
        assert files(output) == before


def test_in_memory_timing_edit_after_review_is_not_silently_exported(asset, monkeypatch, tmp_path):
    sprite, exporter = asset
    replace_frame(sprite)
    before = files(exporter.output_dir)
    widget = DummyExportWidget(str(tmp_path))

    def confirm(plan):
        sprite.animations["attack"].fps = 30
        return True

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    with pytest.raises(ValueError, match="changed"):
        widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    assert files(exporter.output_dir) == before


def test_animation_rename_does_not_claim_unchanged_frames_were_added(asset):
    from spritesage.godot_export_review import friendly_changes

    sprite, exporter = asset
    sprite.animations["strike"] = sprite.animations.pop("attack")
    review = exporter.review()
    summary = "\n".join(friendly_changes(review.updates)).lower()
    assert "rename animation" in summary
    assert "added animation frame" not in summary
    assert "changed artwork" not in summary


def test_project_cannot_add_unreviewed_sprites_after_confirmation(asset, monkeypatch, tmp_path):
    sprite, _ = asset
    project = tmp_path / "source"
    project.mkdir()
    sprite.save(str(project / "hero.sprite"), str(project))
    output = tmp_path / "exports"
    exporter = GodotProjectExporter(str(project), str(output))
    exporter.export()
    replace_frame(sprite)
    before = files(output)
    widget = DummyExportWidget(str(tmp_path))

    def confirm(plan):
        sprite.name = "Unreviewed"
        sprite.save(str(project / "unreviewed.sprite"), str(project))
        return True

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    with pytest.raises(ValueError, match="changed"):
        widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn(), project=True)
    assert files(output) == before

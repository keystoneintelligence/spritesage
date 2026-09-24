"""Timing survives import, editing, persistence, preview, and both Godot exports."""

import json
from pathlib import Path
import re

import pytest
from PIL import Image
from PySide6 import QtWidgets

from spritesage import animation_service as edits
from spritesage.art_importer import import_aseprite_json, import_image_sequence
from spritesage.config import APP_PALETTE
from spritesage.exporter import GodotSpriteExporter
from spritesage.model_baker.animations import frame_times
from spritesage.model_baker.godot_exporter import export_godot_sprite
from spritesage.model_baker.sprite_writer import write_sprite_file_from_manifest
from spritesage.model_baker.timing import animation_from_manifest
from spritesage.sage_file import SageFile
from spritesage.sprite_editor import AnimationPreviewWidget, SpriteEditorView
from spritesage.sprite_file import Animation, SpriteFile
from spritesage.persistence import recovery_path


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def sprite_with(animation, base=""):
    return SpriteFile("timing", "Hero", "", 8, 8, base, {animation.name: animation}, bool(base))


def images(tmp_path, count=3):
    paths = []
    for index in range(count):
        path = tmp_path / f"frame_{index}.png"
        image = Image.new("RGBA", (8, 8))
        image.putpixel((1, 1), (index * 60, 255, 0, 255))
        image.save(path)
        paths.append(str(path))
    return paths


def exported_timing(path):
    text = Path(path).read_text(encoding="utf-8")
    fps = float(re.search(r'"speed": ([\d.e+-]+)', text)[1])
    holds = [float(value) for value in re.findall(r'"duration": ([\d.e+-]+)', text)]
    loop = re.search(r'"loop": (true|false)', text)[1] == "true"
    return fps, [hold / fps for hold in holds], loop


def test_legacy_defaults_and_versioned_round_trip(tmp_path):
    legacy = dict(
        uuid="old",
        name="Hero",
        description="",
        width=8,
        height=8,
        base_image="base.png",
        animations={"walk": ["frames/a.png", "frames/a.png"]},
    )
    sprite = SpriteFile.from_dict(legacy, str(tmp_path))
    path = tmp_path / "hero.sprite"
    path.write_text(json.dumps(legacy))
    assert SpriteFile.from_json(str(path), str(tmp_path)) == sprite
    assert json.loads(path.read_text()) == legacy
    animation = sprite.animations["walk"]
    assert (animation.fps, animation.loop, animation.frame_durations) == (2, True, [1, 1])
    animation.fps = 12.5
    animation.loop = False
    animation.frame_durations = [1, 2.5]
    animation.base_frame_duration = 3
    sprite.save(str(path), str(tmp_path))
    assert json.loads(recovery_path(path).read_text()) == legacy
    record = json.loads(path.read_text())
    assert record["format_version"] == 2
    assert record["animations"]["walk"]["frames"] == [
        {"path": "frames/a.png", "duration": 1},
        {"path": "frames/a.png", "duration": 2.5},
    ]
    restored = SpriteFile.from_json(str(path), str(tmp_path))
    assert restored == sprite
    playback = restored.get_animation_playback("walk")
    assert playback.frame_durations == [3, 1, 2.5]
    assert playback.frame_seconds(0) == pytest.approx(0.24)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fps", 0),
        ("fps", -1),
        ("fps", float("nan")),
        ("fps", float("inf")),
        ("fps", "12"),
        ("fps", True),
        ("loop", "false"),
        ("frame_durations", [0]),
        ("frame_durations", [float("nan")]),
        ("frame_durations", [1, 2]),
        ("base_frame_duration", -1),
    ],
)
def test_invalid_timing_is_rejected(field, value):
    with pytest.raises(ValueError):
        Animation("walk", ["a.png"], **{field: value})


@pytest.mark.parametrize("version", [0, 3, "2", True])
def test_unknown_format_is_not_silently_downgraded(tmp_path, version):
    record = sprite_with(Animation("walk", [])).to_dict(str(tmp_path))
    record["format_version"] = version
    with pytest.raises(ValueError, match="format version"):
        SpriteFile.from_dict(record, str(tmp_path))


def test_frame_edits_keep_each_occurrence_and_its_timing_together():
    sprite = sprite_with(Animation("walk", ["a", "b", "a"], 10, False, [1, 2, 3]))
    edits.reorder_frame(sprite, "walk", 0, 2)
    assert sprite.animations["walk"].frame_durations == [2, 3, 1]
    edits.duplicate_frame(sprite, "walk", 1, "a-copy")
    assert sprite.animations["walk"].frame_durations == [2, 3, 3, 1]
    edits.remove_frame_indices(sprite, "walk", [1])
    edits.move_frame(sprite, "walk", 2, -1)
    edits.reverse_animation_frames(sprite, "walk")
    assert sprite.animations["walk"].frames == ["a-copy", "a", "b"]
    assert sprite.animations["walk"].frame_durations == [3, 1, 2]
    edits.make_ping_pong_loop(sprite, "walk")
    assert sprite.animations["walk"].frame_durations == [3, 1, 2, 1]
    edits.insert_frames(sprite, "walk", 1, ["new"])
    assert sprite.animations["walk"].frame_durations == [3, 1, 1, 2, 1]
    edits.remove_frames(sprite, "walk", ["a"])
    animation = sprite.animations["walk"]
    assert animation.frames == ["a-copy", "new", "b"]
    assert animation.frame_durations == [3, 1, 2]
    assert (animation.fps, animation.loop) == (10, True)


@pytest.mark.parametrize(
    "direction,order",
    [
        ("forward", [0, 1, 2]),
        ("reverse", [2, 1, 0]),
        ("pingpong", [0, 1, 2]),
        ("pingpong_reverse", [2, 1, 0]),
    ],
)
def test_aseprite_timing_matches_preview_and_export(tmp_path, qapp, direction, order):
    sheet = tmp_path / "sheet.png"
    Image.new("RGBA", (24, 8)).save(sheet)
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "frames": [
                    {"frame": {"x": i * 8, "y": 0, "w": 8, "h": 8}, "duration": duration}
                    for i, duration in enumerate([80, 160, 240])
                ],
                "meta": {
                    "image": "sheet.png",
                    "frameTags": [
                        {"name": "walk", "from": 0, "to": 2, "direction": direction, "repeat": "1"}
                    ],
                },
            }
        )
    )
    result = import_aseprite_json(project_dir=tmp_path, sprite_name="Hero", json_path=source)
    sprite = SpriteFile.from_json(str(result.sprite_path), str(tmp_path))
    animation = sprite.get_animation_playback("walk")
    seconds = [[0.08, 0.16, 0.24][index] for index in order]
    assert [animation.frame_seconds(i) for i in range(len(order))] == pytest.approx(seconds)
    assert animation.loop is False
    preview = AnimationPreviewWidget(APP_PALETTE)
    preview.load_animation(animation.frames, str(tmp_path), animation=animation)
    for milliseconds in (round(value * 1000) for value in seconds):
        assert preview.timer.interval() == milliseconds
        preview._next_frame()
    assert not preview.timer.isActive()
    assert preview.current_frame_index == len(order) - 1
    preview.set_playing(True)
    assert preview.current_frame_index == 0
    preview.set_playing(False)
    preview.close()
    GodotSpriteExporter(sprite, str(tmp_path / "export")).export()
    fps, exported_seconds, loop = exported_timing(tmp_path / "export/Hero_frames.tres")
    assert fps == 12.5
    assert exported_seconds == pytest.approx(seconds)
    assert loop is False


@pytest.mark.parametrize(
    "repeat,expected_frames,loop", [(None, 3, False), (0, 3, True), (2, 9, False)]
)
def test_gif_import_preserves_frames_durations_and_repetition(
    tmp_path, repeat, expected_frames, loop
):
    frames = [Image.new("RGBA", (8, 8), (index * 80, 255, 0, 255)) for index in range(3)]
    path = tmp_path / "walk.gif"
    options = {} if repeat is None else {"loop": repeat}
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=[80, 160, 240], **options
    )
    result = import_image_sequence(
        project_dir=tmp_path, sprite_name="Hero", animation_name="walk", image_paths=[path]
    )
    animation = SpriteFile.from_json(str(result.sprite_path), str(tmp_path)).animations["walk"]
    assert len(animation.frames) == expected_frames
    assert animation.loop is loop
    assert [animation.frame_seconds(i) for i in range(expected_frames)] == pytest.approx(
        [0.08, 0.16, 0.24] * (expected_frames // 3)
    )


def test_baked_timing_is_identical_in_direct_and_project_export(tmp_path):
    paths = images(tmp_path)
    sheet = tmp_path / "sheet.png"
    Image.new("RGBA", (24, 8)).save(sheet)
    record = {
        "name": "walk",
        "duration": 0.30,
        "times": [0, 0.125, 0.25],
        "fps": 8,
        "loop": False,
        "sheet": str(sheet),
        "views": {"front": paths},
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"fps": 12, "size": 8, "animations": [record]}))
    result = write_sprite_file_from_manifest(
        manifest, sprite_path=tmp_path / "Hero.sprite", project_dir=tmp_path
    )
    sprite = SpriteFile.from_json(str(result.sprite_path), str(tmp_path))
    GodotSpriteExporter(sprite, str(tmp_path / "project-export")).export()
    direct = export_godot_sprite(
        output_dir=tmp_path, sprite_name="Hero", animations=[record], cell_size=8, fps=12
    )
    direct_timing = exported_timing(direct.sprite_frames_path)
    project_timing = exported_timing(tmp_path / "project-export/Hero_frames.tres")
    assert direct_timing == project_timing
    assert direct_timing[0] == 8
    assert direct_timing[1] == pytest.approx([0.125, 0.125, 0.05])
    assert direct_timing[2] is False


def test_baking_has_no_extra_endpoint_hold_and_frame_cap_keeps_clip_duration():
    assert frame_times(0.25, 8) == [0, 0.125]
    times = frame_times(1, 8, max_frames=3)
    assert times == pytest.approx([0, 1 / 3, 2 / 3])
    animation = animation_from_manifest(
        {"name": "walk", "times": times, "duration": 1},
        name="walk",
        frames=["a", "b", "c"],
        default_fps=8,
    )
    assert sum(animation.frame_durations) / animation.fps == pytest.approx(1)


def test_timing_controls_save_switch_and_undo_without_losing_selection(tmp_path, qapp):
    paths = images(tmp_path)
    sprite = sprite_with(Animation("walk", paths, 8, False, [1, 2, 3]), paths[0])
    sprite.animations["idle"] = Animation("idle", paths[:1], 4)
    path = tmp_path / "Hero.sprite"
    sprite.save(str(path), str(tmp_path))
    project = tmp_path / "project.sage"
    project.write_text(json.dumps({"Project Name": "Test"}))
    view = SpriteEditorView(APP_PALETTE)
    view.load_sprite_data(str(path), SageFile.from_json(str(project)))
    view.anim_list_widget.setCurrentRow(1)
    view.frame_list_widget.setCurrentRow(1)
    assert view.preview_fps_spin.value() == 8
    assert view.frame_duration_spin.value() == 250
    view.frame_duration_spin.setValue(375)
    assert SpriteFile.from_json(str(path), str(tmp_path)).animations["walk"].frame_durations == [
        1,
        3,
        3,
    ]
    view.undo()
    assert view.sprite_data.animations["walk"].frame_durations == [1, 2, 3]
    assert view.anim_list_widget.currentItem().text() == "walk"
    assert view.frame_list_widget.currentRow() == 1
    view.redo()
    view.preview_fps_spin.setValue(12.5)
    assert view.frame_duration_spin.value() == 240
    view.animation_loop_check.setChecked(True)
    view.frame_list_widget.move_frame(1, 0)
    assert view.sprite_data.animations["walk"].frame_durations == [3, 1, 3]
    view.base_frame_button.click()
    view.frame_duration_spin.setValue(160)
    assert view.sprite_data.animations["walk"].base_frame_duration == 2
    view.reset_frame_duration_button.click()
    assert view.sprite_data.animations["walk"].base_frame_duration == 1
    view.anim_list_widget.setCurrentRow(0)
    assert view.preview_fps_spin.value() == 4
    view.anim_list_widget.setCurrentRow(1)
    assert view.preview_fps_spin.value() == 12.5
    assert view.animation_loop_check.isChecked()
    restored = SpriteFile.from_json(str(path), str(tmp_path))
    assert restored == view.sprite_data
    view.close()


def test_looping_and_single_frame_one_shot_preview(tmp_path, qapp):
    paths = images(tmp_path, 1)
    preview = AnimationPreviewWidget(APP_PALETTE)
    for loop in (True, False):
        preview.load_animation(
            paths, str(tmp_path), animation=Animation("idle", paths, 4, loop, [2])
        )
        preview.set_playing(True)
        assert preview.timer.interval() == 500
        preview._next_frame()
        assert preview.timer.isActive() is loop
        assert preview.current_frame_index == 0
    preview.close()


@pytest.mark.parametrize(
    "repeat,order,loop",
    [
        (0, [0, 1, 2, 1], True),
        (1, [0, 1, 2], False),
        (2, [0, 1, 2, 1, 0], False),
        (3, [0, 1, 2, 1, 0, 1, 2], False),
    ],
)
def test_aseprite_ping_pong_repeat_counts_traversals(tmp_path, repeat, order, loop):
    Image.new("RGBA", (24, 8)).save(tmp_path / "sheet.png")
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "frames": [
                    {"frame": {"x": i * 8, "y": 0, "w": 8, "h": 8}, "duration": (i + 1) * 100}
                    for i in range(3)
                ],
                "meta": {
                    "image": "sheet.png",
                    "frameTags": [
                        {
                            "name": "walk",
                            "from": 0,
                            "to": 2,
                            "direction": "pingpong",
                            "repeat": str(repeat),
                        }
                    ],
                },
            }
        )
    )
    result = import_aseprite_json(project_dir=tmp_path, sprite_name="Hero", json_path=source)
    animation = SpriteFile.from_json(str(result.sprite_path), str(tmp_path)).animations["walk"]
    assert animation.frame_durations == [index + 1 for index in order]
    assert animation.loop is loop


@pytest.mark.parametrize("repeat,expected_count,loop", [(0, 3, True), (1, 3, False), (2, 6, False)])
def test_webp_import_preserves_variable_timing_and_total_play_count(
    tmp_path, repeat, expected_count, loop
):
    frames = [Image.new("RGBA", (8, 8), (index * 80, 255, 0, 255)) for index in range(3)]
    path = tmp_path / "walk.webp"
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=[80, 160, 240], loop=repeat
    )
    result = import_image_sequence(
        project_dir=tmp_path, sprite_name="Hero", animation_name="walk", image_paths=[path]
    )
    animation = SpriteFile.from_json(str(result.sprite_path), str(tmp_path)).animations["walk"]
    assert len(animation.frames) == expected_count
    assert animation.loop is loop
    assert [animation.frame_seconds(i) for i in range(expected_count)] == pytest.approx(
        [0.08, 0.16, 0.24] * (expected_count // 3)
    )


def test_timing_save_failure_restores_document_and_controls(tmp_path, qapp, monkeypatch):
    from spritesage import sprite_editor

    path = tmp_path / "Hero.sprite"
    sprite = sprite_with(Animation("walk", images(tmp_path), 8, False, [1, 2, 3]))
    sprite.save(str(path), str(tmp_path))
    project = tmp_path / "project.sage"
    project.write_text(json.dumps({"Project Name": "Test"}))
    view = SpriteEditorView(APP_PALETTE)
    view.load_sprite_data(str(path), SageFile.from_json(str(project)))
    messages = []
    monkeypatch.setattr(
        sprite_editor.QMessageBox, "critical", lambda *args: messages.append(args[1])
    )
    monkeypatch.setattr(view, "save", lambda **kwargs: False)
    view.preview_fps_spin.setValue(20)
    assert view.sprite_data == sprite
    assert view.preview_fps_spin.value() == 8
    assert view.animation_preview.animation.fps == 8
    assert SpriteFile.from_json(str(path), str(tmp_path)) == sprite
    assert messages == ["Could not save timing"]
    assert not view.undo_redo_state().can_undo
    view.close()


def test_preview_carries_fractional_milliseconds_between_frames(tmp_path, qapp):
    paths = images(tmp_path)
    preview = AnimationPreviewWidget(APP_PALETTE)
    preview.load_animation(paths, str(tmp_path), animation=Animation("walk", paths, 3))
    intervals = []
    for _ in range(6):
        intervals.append(preview.timer.interval())
        preview._next_frame()
    assert intervals == [333, 334, 333, 333, 334, 333]
    assert sum(intervals) == 2000
    preview.set_playing(False)
    preview.close()

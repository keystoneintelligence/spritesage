import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image
from PySide6 import QtWidgets

from spritesage import config
from spritesage.art_import_dialog import ArtImportDialog
from spritesage.art_importer import (
    import_aseprite_json,
    import_folder,
    import_image_sequence,
    import_sprite_sheet,
    natural_sorted_paths,
)
from spritesage.sprite_file import SpriteFile


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_art_import_dialog_uses_shared_popup_style(qapp, tmp_path):
    dialog = ArtImportDialog(tmp_path, config.APP_PALETTE)

    assert dialog.objectName() == "SpriteSagePopupDialog"
    assert dialog.windowTitle() == "Import Existing Art"
    assert dialog.findChild(QtWidgets.QTabWidget) is dialog.tabs
    assert "QDialog#SpriteSagePopupDialog QTabWidget::pane" in dialog.styleSheet()


def test_art_import_dialog_builds_requests_for_each_mode(qapp, tmp_path):
    dialog = ArtImportDialog(tmp_path, config.APP_PALETTE)
    sequence_frame = tmp_path / "source" / "walk_1.png"
    sheet_path = tmp_path / "sheet.png"
    folder_path = tmp_path / "folder"
    json_path = tmp_path / "rogue.json"
    aseprite_sheet_path = tmp_path / "rogue.png"

    dialog.sprite_name_edit.setText("Hero")
    dialog.sequence_files = [sequence_frame]
    dialog.sequence_animation_edit.setText("walk")
    dialog.tabs.setCurrentIndex(0)
    request = dialog.to_request()
    assert request.mode == "sequence"
    assert request.options["sprite_name"] == "Hero"
    assert request.options["animation_name"] == "walk"
    assert request.options["image_paths"] == (sequence_frame,)

    dialog.folder_path_edit.setText(str(folder_path))
    dialog.folder_animation_edit.setText("idle")
    dialog.tabs.setCurrentIndex(1)
    request = dialog.to_request()
    assert request.mode == "folder"
    assert request.options["folder_path"] == folder_path
    assert request.options["default_animation_name"] == "idle"

    dialog.sheet_path_edit.setText(str(sheet_path))
    dialog.sheet_width_spin.setValue(32)
    dialog.sheet_height_spin.setValue(24)
    dialog.sheet_margin_spin.setValue(2)
    dialog.sheet_spacing_spin.setValue(3)
    dialog.sheet_animation_edit.setText("jump")
    dialog.sheet_ignore_empty_check.setChecked(False)
    dialog.tabs.setCurrentIndex(2)
    request = dialog.to_request()
    assert request.mode == "sheet"
    assert request.options["sheet_path"] == sheet_path
    assert request.options["frame_width"] == 32
    assert request.options["frame_height"] == 24
    assert request.options["margin"] == 2
    assert request.options["spacing"] == 3
    assert request.options["animation_name"] == "jump"
    assert request.options["ignore_empty"] is False

    dialog.aseprite_json_edit.setText(str(json_path))
    dialog.aseprite_sheet_edit.setText(str(aseprite_sheet_path))
    dialog.tabs.setCurrentIndex(3)
    request = dialog.to_request()
    assert request.mode == "aseprite"
    assert request.options["json_path"] == json_path
    assert request.options["sheet_path"] == aseprite_sheet_path


def test_art_import_dialog_validation_blocks_empty_sprite_name(qapp, tmp_path, monkeypatch):
    dialog = ArtImportDialog(tmp_path, config.APP_PALETTE)
    errors = []
    monkeypatch.setattr(dialog, "_show_validation_error", errors.append)

    dialog.accept()

    assert errors == ["Enter a sprite name."]
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected


def _write_image(path: Path, size=(8, 8), color=(255, 0, 0, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _new_rgba(size, color).save(path)
    return path


def _new_rgba(
    size: tuple[int, int],
    color: tuple[int, int, int, int],
) -> Image.Image:
    return Image.new("RGBA", size, cast(Any, color))


def test_natural_sorted_paths_orders_numbered_frames():
    paths = [Path("idle_10.png"), Path("idle_1.png"), Path("idle_2.png")]

    assert [path.name for path in natural_sorted_paths(paths)] == [
        "idle_1.png",
        "idle_2.png",
        "idle_10.png",
    ]


def test_import_image_sequence_creates_project_relative_sprite(tmp_path):
    source_dir = tmp_path / "source"
    frame_10 = _write_image(source_dir / "walk_10.png", size=(12, 10), color=(0, 0, 255, 255))
    frame_1 = _write_image(source_dir / "walk_1.png", size=(12, 10), color=(255, 0, 0, 255))
    frame_2 = _write_image(source_dir / "walk_2.png", size=(12, 10), color=(0, 255, 0, 255))
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = import_image_sequence(
        project_dir=project_dir,
        sprite_name="Hero",
        animation_name="walk",
        image_paths=[frame_10, frame_1, frame_2],
    )

    assert result.sprite_path == project_dir / "Hero.sprite"
    assert result.asset_dir == project_dir / "sprites" / "Hero"
    assert result.frame_count == 3
    assert result.animation_names == ("walk",)

    data = json.loads(result.sprite_path.read_text(encoding="utf-8"))
    assert data["name"] == "Hero"
    assert data["width"] == 12
    assert data["height"] == 10
    assert os.path.normpath(data["base_image"]) == os.path.normpath(
        "sprites/Hero/animations/walk/frame_000.png"
    )
    assert data["include_base_image_in_animations"] is False
    assert data["animations"]["walk"] == [
        os.path.normpath("sprites/Hero/animations/walk/frame_000.png"),
        os.path.normpath("sprites/Hero/animations/walk/frame_001.png"),
        os.path.normpath("sprites/Hero/animations/walk/frame_002.png"),
    ]

    loaded = SpriteFile.from_json(str(result.sprite_path), str(project_dir))
    expected_base = project_dir / "sprites" / "Hero" / "animations" / "walk" / "frame_000.png"
    assert loaded.base_image == str(expected_base)
    assert [Path(path).name for path in loaded.get_animation_frames("walk")] == [
        "frame_000.png",
        "frame_001.png",
        "frame_002.png",
    ]
    assert loaded.get_animation_playback_frames("walk") == loaded.get_animation_frames("walk")


def test_import_folder_uses_subfolders_as_animations(tmp_path):
    source_dir = tmp_path / "source"
    _write_image(source_dir / "idle" / "idle_2.png")
    _write_image(source_dir / "idle" / "idle_10.png")
    _write_image(source_dir / "idle" / "idle_1.png")
    _write_image(source_dir / "walk" / "walk_1.png")
    _write_image(source_dir / "walk" / "walk_2.png")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = import_folder(
        project_dir=project_dir,
        sprite_name="Knight",
        folder_path=source_dir,
    )

    loaded = SpriteFile.from_json(str(result.sprite_path), str(project_dir))
    assert set(loaded.animations.keys()) == {"idle", "walk"}
    assert [Path(path).name for path in loaded.get_animation_frames("idle")] == [
        "frame_000.png",
        "frame_001.png",
        "frame_002.png",
    ]
    assert len(loaded.get_animation_frames("walk")) == 2


def test_import_sprite_sheet_slices_fixed_grid_and_skips_transparent_frames(tmp_path):
    sheet_path = tmp_path / "sheet.png"
    sheet = _new_rgba((12, 4), (0, 0, 0, 0))
    sheet.paste(_new_rgba((4, 4), (255, 0, 0, 255)), (0, 0))
    sheet.paste(_new_rgba((4, 4), (0, 255, 0, 255)), (8, 0))
    sheet.save(sheet_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = import_sprite_sheet(
        project_dir=project_dir,
        sprite_name="Slime",
        sheet_path=sheet_path,
        frame_width=4,
        frame_height=4,
        animation_name="idle",
    )

    loaded = SpriteFile.from_json(str(result.sprite_path), str(project_dir))
    assert result.frame_count == 2
    assert loaded.width == 4
    assert loaded.height == 4
    assert len(loaded.get_animation_frames("idle")) == 2


def test_import_aseprite_json_uses_frame_tags_as_animations(tmp_path):
    source_dir = tmp_path / "source"
    sheet_path = source_dir / "rogue.png"
    sheet = _new_rgba((12, 4), (0, 0, 0, 0))
    sheet.paste(_new_rgba((4, 4), (255, 0, 0, 255)), (0, 0))
    sheet.paste(_new_rgba((4, 4), (0, 255, 0, 255)), (4, 0))
    sheet.paste(_new_rgba((4, 4), (0, 0, 255, 255)), (8, 0))
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path)
    json_path = source_dir / "rogue.json"
    json_path.write_text(
        json.dumps(
            {
                "frames": {
                    "rogue_0.aseprite": {"frame": {"x": 0, "y": 0, "w": 4, "h": 4}},
                    "rogue_1.aseprite": {"frame": {"x": 4, "y": 0, "w": 4, "h": 4}},
                    "rogue_2.aseprite": {"frame": {"x": 8, "y": 0, "w": 4, "h": 4}},
                },
                "meta": {
                    "image": "rogue.png",
                    "frameTags": [
                        {"name": "idle", "from": 0, "to": 1, "direction": "forward"},
                        {"name": "blink", "from": 2, "to": 2, "direction": "forward"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = import_aseprite_json(
        project_dir=project_dir,
        sprite_name="Rogue",
        json_path=json_path,
    )

    loaded = SpriteFile.from_json(str(result.sprite_path), str(project_dir))
    assert result.frame_count == 3
    assert set(loaded.animations.keys()) == {"idle", "blink"}
    assert len(loaded.get_animation_frames("idle")) == 2
    assert len(loaded.get_animation_frames("blink")) == 1


def test_import_generates_unique_sprite_and_asset_paths(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "Hero.sprite").write_text("existing", encoding="utf-8")
    (project_dir / "sprites" / "Hero").mkdir(parents=True)
    frame = _write_image(tmp_path / "source" / "idle_1.png")

    result = import_image_sequence(
        project_dir=project_dir,
        sprite_name="Hero",
        animation_name="idle",
        image_paths=[frame],
    )

    assert result.sprite_path == project_dir / "Hero_2.sprite"
    assert result.asset_dir == project_dir / "sprites" / "Hero_2"
    assert (project_dir / "Hero.sprite").read_text(encoding="utf-8") == "existing"
    assert result.sprite_path.exists()

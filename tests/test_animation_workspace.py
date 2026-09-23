"""Interaction, pixel fidelity, export, and layout persistence regressions."""

import json
from typing import Any, cast

import pytest
from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets, QtTest

from spritesage.animation_widgets import PixelCanvas
from spritesage.config import APP_PALETTE
from spritesage.exporter import GodotSpriteExporter
from spritesage.sage_file import SageFile
from spritesage.sprite_editor import SpriteEditorView
from spritesage.sprite_file import SpriteFile, Animation
from spritesage.spritesheet import SpriteSheetGenerator


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def workspace(qapp, tmp_path):
    paths = []
    for index, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"frame{index}.png"
        image = Image.new("RGBA", (12, 9), cast(Any, color))
        image.putpixel((0, 0), (0, 0, 0, 0))
        image.save(path)
        paths.append(str(path))
    sprite = SpriteFile(
        "test",
        "Hero",
        "",
        24,
        18,
        paths[0],
        {
            "empty": Animation("empty", []),
            "walk": Animation("walk", paths),
        },
        include_base_image_in_animations=False,
    )
    path = tmp_path / "hero.sprite"
    sprite.save(str(path), str(tmp_path))
    project = tmp_path / "project.sage"
    project.write_text(json.dumps({"Project Name": "Test"}))
    view = SpriteEditorView(APP_PALETTE)
    view.load_sprite_data(str(path), SageFile.from_json(str(project)))
    view.sprite_tabs.setCurrentWidget(view.animations_tab)
    view.anim_list_widget.setCurrentRow(1)
    view.resize(760, 640)
    view.show()
    qapp.processEvents()
    yield view
    view.close()
    view.deleteLater()
    qapp.processEvents()


def test_reorder_saves_exact_order_with_repeated_paths_and_undo(workspace):
    view = workspace
    paths = view.sprite_data.animations["walk"].frames.copy()
    view.sprite_data.animations["walk"].frames = [paths[0], paths[1], paths[0]]
    view.save()
    view._reload_current_frame_list(1)
    view.frame_list_widget.move_frame(1, 2)
    assert view.sprite_data.animations["walk"].frames == [paths[0], paths[0], paths[1]]
    assert view.frame_list_widget.currentRow() == 2
    saved = SpriteFile.from_json(view.current_file_path, view.sage_file.directory)
    assert saved.animations == view.sprite_data.animations
    view.undo()
    assert view.anim_list_widget.currentItem().text() == "walk"
    assert view.sprite_data.animations["walk"].frames == [paths[0], paths[1], paths[0]]
    view.redo()
    assert view.sprite_data.animations["walk"].frames == [paths[0], paths[0], paths[1]]


def test_drop_between_thumbnails_and_at_end(workspace):
    timeline = workspace.frame_list_widget
    timeline.setCurrentRow(0)

    class Drop:
        accepted = False

        def source(self):
            return timeline

        def position(self):
            return QtCore.QPointF(timeline.visualItemRect(timeline.item(2)).right() + 6, 30)

        def setDropAction(self, action):
            assert action == QtCore.Qt.DropAction.MoveAction

        def accept(self):
            self.accepted = True

    event = Drop()
    first = workspace.sprite_data.animations["walk"].frames[0]
    timeline.dropEvent(event)
    assert event.accepted
    assert workspace.sprite_data.animations["walk"].frames[-1] == first
    assert timeline.currentRow() == 2
    assert timeline._insertion_index(timeline.visualItemRect(timeline.item(1)).topLeft()) == 1


def test_play_pause_step_selection_and_keyboard(workspace, qapp):
    view = workspace
    preview = view.animation_preview
    view.play_pause_button.click()
    assert preview.timer.isActive() and view.play_pause_button.text() == "Pause"
    preview._next_frame()
    assert view.frame_list_widget.currentRow() == 1
    # Clicking the already-current frame must still pause playback.
    QtTest.QTest.mouseClick(
        view.frame_list_widget.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=view.frame_list_widget.visualItemRect(view.frame_list_widget.item(1)).center(),
    )
    assert not preview.timer.isActive()
    QtTest.QTest.keyClick(view.frame_list_widget, QtCore.Qt.Key.Key_Right)
    assert preview.current_frame_index == 2 and view.frame_list_widget.currentRow() == 2
    view.next_frame_button.click()
    assert preview.current_frame_index == 0
    QtTest.QTest.keyClick(view.frame_list_widget, QtCore.Qt.Key.Key_Space)
    assert preview.timer.isActive()
    view.preview_fps_spin.setValue(20)
    assert preview.timer.interval() == 50
    view.sprite_tabs.setCurrentWidget(view.info_tab)
    qapp.processEvents()
    assert not preview.timer.isActive()


def test_missing_frame_and_base_keep_playhead_indices(workspace, tmp_path):
    view = workspace
    paths = view.sprite_data.animations["walk"].frames
    paths[1] = str(tmp_path / "missing.png")
    view._reload_current_frame_list(0)
    view.include_base_image_check.setChecked(True)
    preview = view.animation_preview
    assert len(preview.pixmaps) == 4
    view.frame_list_widget.setCurrentRow(1)
    assert preview.current_frame_index == 2
    assert "Could not load" in preview.image_label.text()
    view.next_frame_button.click()
    assert preview.current_frame_index == 3 and view.frame_list_widget.currentRow() == 2
    view.next_frame_button.click()
    assert preview.current_frame_index == 0
    assert view.base_frame_button.isChecked()
    assert view.frame_list_widget.currentRow() == -1
    assert not view.remove_frame_button.isEnabled()
    view.next_frame_button.click()
    assert preview.current_frame_index == 1 and view.frame_list_widget.currentRow() == 0


def test_empty_animation_and_switching_never_restore_stale_frames(workspace, qapp):
    view = workspace
    view.zoom_combo.setCurrentIndex(view.zoom_combo.findData(16))
    view.play_pause_button.click()
    view.anim_list_widget.setCurrentRow(0)
    qapp.processEvents()
    assert not view.animation_preview.pixmaps
    assert not view.play_pause_button.isEnabled()
    assert not view.next_frame_button.isEnabled()
    assert not view.remove_frame_button.isEnabled()
    assert view.add_frames_button.isEnabled()
    assert "no frames" in view.animation_preview.image_label.text()
    assert view.animation_preview.image_label.minimumSize() == QtCore.QSize(100, 100)


def test_space_preserves_native_checkbox_interaction(workspace):
    view = workspace
    view.onion_skin_check.setFocus()
    QtTest.QTest.keyClick(view.onion_skin_check, QtCore.Qt.Key.Key_Space)
    assert view.onion_skin_check.isChecked()
    assert not view.animation_preview.timer.isActive()
    view.animation_preview.image_label.setFocus()
    QtTest.QTest.keyClick(view.animation_preview.image_label, QtCore.Qt.Key.Key_Space)
    assert view.animation_preview.timer.isActive()


def test_cancelled_drag_pauses_playback_without_mutating_frames(workspace, monkeypatch):
    from spritesage import animation_widgets

    view = workspace
    original = view.sprite_data.animations["walk"].frames.copy()

    class CancelledDrag:
        def __init__(self, parent):
            assert parent is view.frame_list_widget

        def setMimeData(self, mime):
            assert mime.hasFormat("application/x-qabstractitemmodeldatalist")

        def setPixmap(self, pixmap):
            assert not pixmap.isNull()

        def exec(self, action):
            assert not view.animation_preview.timer.isActive()
            return QtCore.Qt.DropAction.IgnoreAction

        def deleteLater(self):
            pass

    monkeypatch.setattr(animation_widgets.QtGui, "QDrag", CancelledDrag)
    view.play_pause_button.click()
    view.frame_list_widget.startDrag(QtCore.Qt.DropAction.MoveAction)
    assert view.frame_list_widget.count() == len(original)
    assert view.sprite_data.animations["walk"].frames == original


def test_zoom_preserves_original_pixels_and_allows_scrolling(workspace, qapp):
    view = workspace
    preview = view.animation_preview
    original = preview.pixmaps[0].toImage()
    assert original.size() == QtCore.QSize(12, 9)
    view.zoom_combo.setCurrentIndex(view.zoom_combo.findData(16))
    qapp.processEvents()
    assert preview.image_label.zoom == 16
    assert preview.image_label.minimumWidth() == 12 * 16 + 24
    # A larger source at fixed zoom must be scrollable, without allocating scaled pixmaps.
    image = QtGui.QPixmap(256, 256)
    image.fill(QtCore.Qt.GlobalColor.red)
    preview.pixmaps = [image]
    preview.image_label.canvas_size = image.size()
    preview.show_frame(0)
    qapp.processEvents()
    assert preview.scroll_area.horizontalScrollBar().maximum() > 0
    assert preview.scroll_area.verticalScrollBar().maximum() > 0
    assert preview.image_label.pixmap().size() == image.size()
    view.zoom_combo.setCurrentIndex(0)
    qapp.processEvents()
    assert preview.scroll_area.horizontalScrollBar().maximum() == 0


def test_canvas_nearest_smooth_and_checkerboard_rendering(qapp):
    canvas = PixelCanvas(APP_PALETTE)
    canvas.resize(120, 120)
    source = QtGui.QImage(2, 2, QtGui.QImage.Format.Format_ARGB32)
    for x, y, color in ((0, 0, "red"), (1, 0, "blue"), (0, 1, "green"), (1, 1, "yellow")):
        source.setPixelColor(x, y, QtGui.QColor(color))
    canvas.setPixmap(QtGui.QPixmap.fromImage(source))
    canvas.set_zoom(4)
    canvas.show()
    qapp.processEvents()
    nearest = canvas.grab().toImage()
    colors = {nearest.pixelColor(x, y).name() for x in range(56, 64) for y in range(56, 64)}
    assert colors == {"#ff0000", "#0000ff", "#008000", "#ffff00"}
    assert nearest.pixelColor(1, 1) != nearest.pixelColor(9, 1)
    canvas.pixel_art = False
    smooth = canvas.grab().toImage()
    assert len({smooth.pixelColor(x, y).name() for x in range(56, 64) for y in range(56, 64)}) > 4
    canvas.checkerboard = False
    solid = canvas.grab().toImage()
    assert solid.pixelColor(1, 1) == solid.pixelColor(9, 1)
    canvas.close()


@pytest.mark.parametrize("pixel_art", [True, False])
def test_rendering_setting_persists_and_reaches_export(workspace, tmp_path, pixel_art):
    view = workspace
    view.pixel_art_action.setChecked(pixel_art)
    view.save()
    sprite = SpriteFile.from_json(view.current_file_path, view.sage_file.directory)
    assert sprite.pixel_art is pixel_art
    assert view.animation_preview.image_label.pixel_art is pixel_art
    assert view.edit_preview_label.pixel_art is pixel_art
    GodotSpriteExporter(sprite, str(tmp_path / "export")).export()
    scene = (tmp_path / "export" / "Hero.tscn").read_text()
    assert f"texture_filter = {1 if pixel_art else 2}" in scene


def test_export_preserves_nearest_colors_and_partial_alpha(workspace, tmp_path):
    sprite = workspace.sprite_data
    path = tmp_path / "alpha.png"
    image = Image.new("RGBA", (2, 2), cast(Any, (255, 0, 0, 128)))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.putpixel((1, 0), (0, 0, 255, 255))
    image.save(path)
    sprite.animations = {"idle": Animation("idle", [str(path)])}
    sprite.width = sprite.height = 8
    output = tmp_path / "sheet.png"
    SpriteSheetGenerator(sprite).create_spritesheet(str(output))
    with Image.open(output) as sheet:
        assert sheet.getpixel((1, 6)) == (255, 0, 0, 128)
        assert sheet.getpixel((6, 1)) == (0, 0, 255, 255)
        assert sheet.getpixel((1, 1))[3] == 0


def test_console_and_panel_sizes_restore(qapp, tmp_path, monkeypatch):
    from spritesage import main_window

    path = tmp_path / "preferences.json"
    monkeypatch.setattr(main_window, "SETTINGS_FILE_NAME", str(path))
    monkeypatch.setattr(main_window, "refresh_model_cache_for_settings", lambda _: {})
    window = main_window.MainWindow()
    window.show()
    qapp.processEvents()
    assert window.bottom_splitter.isHidden()
    assert window.logo_widget.isHidden()
    window.console_toggle.click()
    qapp.processEvents()
    assert window.console_action.isChecked()
    assert window.outer_splitter.sizes()[1] >= 100
    window.inner_splitter.setSizes([290, 710])
    sprite = window.editor_widget.sprite_editor
    window.editor_widget.stacked_layout.setCurrentWidget(sprite)
    sprite.sprite_tabs.setCurrentWidget(sprite.animations_tab)
    qapp.processEvents()
    sprite.preview_splitter.setSizes([200, 480])
    sprite.animation_splitter.setSizes([280, 230])
    window.outer_splitter.setSizes([480, 200])
    window.console_toggle.click()
    window.close()
    saved = json.loads(path.read_text())["Workspace layout"]
    assert saved["console_visible"] is False
    restored = main_window.MainWindow()
    restored.show()
    qapp.processEvents()
    assert abs(restored.inner_splitter.sizes()[0] - saved["sidebar"][0]) <= 2
    sprite = restored.editor_widget.sprite_editor
    restored.editor_widget.stacked_layout.setCurrentWidget(sprite)
    sprite.sprite_tabs.setCurrentWidget(sprite.animations_tab)
    restored.console_action.trigger()
    qapp.processEvents()
    assert abs(restored.outer_splitter.sizes()[1] - saved["console_sizes"][1]) <= 3
    assert abs(sprite.preview_splitter.sizes()[0] - saved["preview"][0]) <= 3
    assert abs(sprite.animation_splitter.sizes()[1] - saved["animation"][1]) <= 3
    restored.close()


def test_corrupt_layout_preferences_fall_back(qapp, tmp_path, monkeypatch):
    from spritesage import main_window

    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps(
            {
                "Workspace layout": {
                    "sidebar": [-1, "bad"],
                    "console_sizes": [0, 0],
                    "animation": None,
                    "preview": "oops",
                }
            }
        )
    )
    monkeypatch.setattr(main_window, "SETTINGS_FILE_NAME", str(path))
    monkeypatch.setattr(main_window, "refresh_model_cache_for_settings", lambda _: {})
    window = main_window.MainWindow()
    window.show()
    qapp.processEvents()
    assert window.bottom_splitter.isHidden()
    assert all(size > 0 for size in window.inner_splitter.sizes())
    window.close()

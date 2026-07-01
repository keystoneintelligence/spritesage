import os
import json
import tempfile
from typing import Any, cast

import pytest

from PySide6 import QtWidgets, QtCore, QtGui

from spritesage import sprite_editor
from spritesage.sprite_editor import AnimationPreviewWidget, SpriteEditorView
from spritesage.sage_editor import SageFile
from spritesage import config


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestAnimationPreviewWidget:
    @pytest.fixture(autouse=True)
    def setup_widget(self):
        # Use default palette for styling
        self.palette = config.APP_PALETTE
        self.widget = AnimationPreviewWidget(self.palette)
        return self.widget

    def test_set_frame_delay_positive(self):
        w = self.widget
        # default delay
        assert w.frame_delay_ms == 500
        # set positive delay
        w.frame_delay_ms = 0
        # simulate timer active
        w.timer.start(100)
        w.set_frame_delay(200)
        assert w.frame_delay_ms == 200
        assert w.timer.isActive()
        w.timer.stop()

    def test_set_frame_delay_nonpositive(self):
        w = self.widget
        w.frame_delay_ms = 400
        # timer not active
        if w.timer.isActive():
            w.timer.stop()
        w.set_frame_delay(0)
        # nonpositive resets to 100
        assert w.frame_delay_ms == 100
        # timer was not active, so remains inactive
        assert not w.timer.isActive()

    def test_load_animation_invalid_base_dir(self, capsys):
        w = self.widget
        # invalid base_dir
        w.load_animation(["a.png"], base_dir="nonexistent_dir")
        out = capsys.readouterr().out
        assert "Invalid base directory" in out
        assert w.image_label.text().startswith("Error:")
        assert not w.pixmaps

    def test_load_animation_empty_paths(self):
        w = self.widget
        # valid base_dir
        tmp = tempfile.mkdtemp()
        w.load_animation([], base_dir=tmp)
        # label should indicate no frames
        assert "no frames" in w.image_label.text()
        assert not w.pixmaps

    def test_load_animation_not_found(self, capsys):
        w = self.widget
        tmp = tempfile.mkdtemp()
        # path does not exist
        w.load_animation(["missing.png"], base_dir=tmp)
        out = capsys.readouterr().out
        assert "Frame image not found" in out
        # label should indicate could not load any frames
        assert "Could not load" in w.image_label.text()
        assert not w.pixmaps

    def test_load_animation_single_frame(self, tmp_path):
        w = self.widget
        # create a small image
        img_path = tmp_path / "f.png"
        pix = QtGui.QPixmap(20, 20)
        pix.fill(QtCore.Qt.GlobalColor.red)
        pix.save(str(img_path))
        # load animation
        w.load_animation([str(img_path)], base_dir=str(tmp_path))
        # one pixmap loaded
        assert len(w.pixmaps) == 1
        # label pixmap is set
        assert isinstance(w.image_label.pixmap(), QtGui.QPixmap)
        # timer should not be active for single frame
        assert not w.timer.isActive()

    def test_load_animation_multiple_frames_and_next(self, tmp_path):
        w = self.widget
        # create two small images
        paths = []
        for i, color in enumerate([QtCore.Qt.GlobalColor.blue, QtCore.Qt.GlobalColor.green]):
            img = tmp_path / f"{i}.png"
            pix = QtGui.QPixmap(20, 20)
            pix.fill(color)
            pix.save(str(img))
            paths.append(str(img))
        # load both
        w.load_animation(paths, base_dir=str(tmp_path))
        assert len(w.pixmaps) == 2
        # timer should be active
        assert w.timer.isActive()
        # advance frame
        w._next_frame()
        assert w.current_frame_index == 1
        # pixmap updated
        assert w.image_label.pixmap().cacheKey() == w.pixmaps[1].cacheKey()
        # cycle back
        w._next_frame()
        assert w.current_frame_index == 0
        # pixmap updated back
        assert w.image_label.pixmap().cacheKey() == w.pixmaps[0].cacheKey()
        w.timer.stop()

    def test_clear_preview(self):
        w = self.widget
        # prepare state
        w.pixmaps = [QtGui.QPixmap(10, 10)]
        w.current_frame_index = 1
        w.image_label.setText("Temp")
        w.image_label.setPixmap(w.pixmaps[0])
        w.timer.start(100)
        # clear
        w.clear_preview()
        assert not w.timer.isActive()
        assert w.pixmaps == []
        assert w.current_frame_index == 0
        # After clear, pixmap is null; text may be cleared by setPixmap
        assert w.image_label.pixmap().isNull()
        # Label text cleared when pixmap set
        assert w.image_label.text() == ""


class TestSpriteEditorView:
    @pytest.fixture(autouse=True)
    def setup_view(self, tmp_path, monkeypatch):
        # Create a temp sage file context
        self.tmp_dir = tmp_path / "prj"
        self.tmp_dir.mkdir()
        # Dummy sage file
        file_path = str(self.tmp_dir / "sprite.spr")
        # Ensure file exists
        open(file_path, "w").write("{}")
        # Add dummy camera argument, to match SageFile.__init__ signature
        self.sage_file = SageFile(
            project_name="p",
            version="v",
            created_at="c",
            project_description="pd",
            keywords="kw",
            camera="dummy_camera",
            reference_images=[],
            last_saved="ls",
            filepath=file_path,
        )

        # Instantiate view
        self.view = SpriteEditorView(config.APP_PALETTE)
        # Inject sage_file and current_file_path
        self.view.sage_file = self.sage_file
        self.view.current_file_path = file_path
        self.view._base_dir = str(self.tmp_dir)

        # Stub base_image_loader
        class DummyLoader:
            def __init__(self):
                self.loaded = []

            def load_image(self, path):
                self.loaded.append(path)

            def get_relative_path(self):
                return self.loaded[-1] if self.loaded else None

            def blockSignals(self, block):
                pass

            def clear_image(self, emit_signal=False):
                pass

        self.dummy_loader = DummyLoader()
        cast(Any, self.view).base_image_loader = self.dummy_loader
        return self.view

    def test_on_base_image_action_clicked_no_desc(self, monkeypatch, capsys):
        v = self.view
        # Ensure desc is empty
        v.desc_edit.setPlainText("")
        # Monkeypatch QMessageBox.warning
        called = {}

        def fake_warning(selfwin, title, text):
            called["warn"] = (title, text)

        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", fake_warning)
        # Call method
        v._on_base_image_action_clicked(index=0)
        # Should warn and abort
        assert "warn" in called
        out = capsys.readouterr().out
        assert "AI generation aborted" in out
        # Loader not called
        assert not self.dummy_loader.loaded

    def test_export_current_sprite_to_godot_writes_under_exports_folder(
        self, monkeypatch, tmp_path
    ):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        v = self.view
        v.sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )
        v.current_file_path = str(sprite_path)
        cast(Any, v).sprite_data = object()
        parsed_sprite = object()
        exporter_calls = []
        completed = []
        progress_callback = object()

        class FakeExporter:
            def __init__(self, sprite_file, output_dir, progress_callback=None):
                exporter_calls.append((sprite_file, output_dir, progress_callback))

            def export(self):
                return None

        def fake_from_json(fpath, sage_directory):
            assert fpath == str(sprite_path)
            assert sage_directory == str(tmp_path)
            return parsed_sprite

        def fake_call_with_progress(parent, fn, *args, **kwargs):
            assert parent is v
            assert kwargs["progress_label"] == "Exporting Godot sprite"
            return fn(progress_callback=progress_callback)

        monkeypatch.setattr(v, "save", lambda: None)
        monkeypatch.setattr(v, "_prompt_for_export_folder_name", lambda default: ("hero", True))
        monkeypatch.setattr(sprite_editor.SpriteFile, "from_json", fake_from_json)
        monkeypatch.setattr(sprite_editor, "GodotSpriteExporter", FakeExporter)
        monkeypatch.setattr(sprite_editor, "call_with_progress", fake_call_with_progress)
        monkeypatch.setattr(
            v,
            "_show_export_complete",
            lambda path, output: completed.append((path, output)),
        )

        v.export_current_sprite_to_godot()

        expected_output_dir = os.path.join(str(tmp_path), "exports", "hero")
        assert exporter_calls == [(parsed_sprite, expected_output_dir, progress_callback)]
        assert completed == [(str(sprite_path), expected_output_dir)]

    def test_disassociate_current_sprite_hides_without_deleting_file(self, monkeypatch, tmp_path):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        sprite_path.write_text("{}", encoding="utf-8")
        v = self.view
        v.sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )
        v.current_file_path = str(sprite_path)
        project_changes = []
        v.project_file_changed.connect(
            lambda before, after, label: project_changes.append((before, after, label))
        )
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
        )

        v._disassociate_current_sprite()

        assert sprite_path.exists()
        assert v.sage_file.hidden_sprites == ["hero.sprite"]
        loaded = json.loads(project_file.read_text(encoding="utf-8"))
        assert loaded["Hidden Sprites"] == ["hero.sprite"]
        assert len(project_changes) == 1
        before, after, label = project_changes[0]
        assert before.hidden_sprites == []
        assert after.hidden_sprites == ["hero.sprite"]
        assert label == "Remove sprite from project"

    def test_on_base_image_action_clicked_ai_none(self, monkeypatch, capsys):
        v = self.view
        # Set description
        v.desc_edit.setPlainText("desc")

        # Dummy AIModelManager with get_active_vendor()
        class DummyVendor:
            def __init__(self, value):
                self.value = value

        class DummyMM:
            def generate_base_sprite_image(self, **kwargs):
                return None

            def get_active_vendor(self):
                return DummyVendor("dummy_vendor")

        monkeypatch.setattr(sprite_editor, "AIModelManager", lambda: DummyMM())
        # Call method
        v._on_base_image_action_clicked(index=1)
        out = capsys.readouterr().out
        # No image returned
        assert "No image returned" in out
        # Base loader not called
        assert not self.dummy_loader.loaded
        # Final log always printed
        assert "triggered AIModelManager" in out

    def test_on_base_image_action_clicked_ai_success(self, monkeypatch, tmp_path, capsys):
        v = self.view
        v.desc_edit.setPlainText("d")

        # Create fake AI image
        ai_img = tmp_path / "gen.png"
        pix = QtGui.QPixmap(10, 10)
        pix.fill(QtCore.Qt.GlobalColor.black)
        pix.save(str(ai_img))

        # Dummy AIModelManager with get_active_vendor()
        class DummyVendor:
            def __init__(self, value):
                self.value = value

        class DummyMM:
            def generate_base_sprite_image(self, **kwargs):
                return str(ai_img)

            def get_active_vendor(self):
                return DummyVendor("dummy_vendor")

        monkeypatch.setattr(sprite_editor, "AIModelManager", lambda: DummyMM())

        # Provide a dummy sprite_data object that has a base_image attribute
        class DummySprite:
            pass

        cast(Any, v).sprite_data = DummySprite()

        # Stub save() so we can verify it gets called
        calls = []
        cast(Any, v).save = lambda *args, **kwargs: calls.append((args, kwargs))

        # Call method
        v._on_base_image_action_clicked(index=2)
        out = capsys.readouterr().out

        # Loader called
        assert self.dummy_loader.loaded and self.dummy_loader.loaded[0] == str(ai_img)

        # save() called
        assert calls
        assert calls[0][1]["label"] == "Generate base image"

        # Final log printed
        assert "triggered AIModelManager" in out

    def test_set_animation_controls_enabled(self, monkeypatch):
        v = self.view
        # Stub update_frame_button_states
        called = []
        monkeypatch.setattr(v, "_update_frame_button_states", lambda: called.append(True))
        # Disable
        v._set_animation_controls_enabled(False)
        assert not v.add_anim_button.isEnabled()
        assert not v.anim_list_widget.isEnabled()
        # Enable
        v._set_animation_controls_enabled(True)
        assert v.add_anim_button.isEnabled()
        # Should call update_frame_button_states once
        assert called

    def test_save_and_file_written(self, tmp_path):
        v = self.view

        # Monkeypatch _get_sprite_data_to_save to return a dummy object
        class DummySpriteData:
            def __init__(self, text):
                self._text = text

            def save(self, fpath, sage_directory):
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(self._text)

        dummy_data = DummySpriteData('{"x":1}')
        cast(Any, v).sprite_data = dummy_data

        # Point current_file_path to tmp
        fp = tmp_path / "out.spr"
        v.current_file_path = str(fp)

        # Override _get_sprite_data_to_save to return our dummy
        cast(Any, v)._get_sprite_data_to_save = lambda: dummy_data

        # Call save()
        v.save()

        # File written
        assert fp.exists()
        assert fp.read_text(encoding="utf-8") == '{"x":1}'

    def test_undo_redo_round_trips_after_redo(self, tmp_path):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        project_file.write_text(json.dumps({"Project Name": "Project"}), encoding="utf-8")
        sprite_path.write_text(
            json.dumps(
                {
                    "uuid": "sprite-1",
                    "name": "Hero",
                    "description": "",
                    "width": 32,
                    "height": 32,
                    "base_image": "",
                    "include_base_image_in_animations": True,
                    "animations": {},
                }
            ),
            encoding="utf-8",
        )
        cast(Any, self.view.base_image_loader).get_absolute_path = lambda: ""
        sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )

        self.view.load_sprite_data(str(sprite_path), sage_file)
        assert not self.view.undo_redo_state().can_undo

        self.view.name_edit.setText("Mage")
        assert self.view.undo_redo_state().can_undo

        self.view.undo()
        assert self.view.name_edit.text() == "Hero"
        assert self.view.undo_redo_state().can_redo

        self.view.redo()
        assert self.view.name_edit.text() == "Mage"
        assert self.view.undo_redo_state().can_undo

        self.view.undo()
        assert self.view.name_edit.text() == "Hero"

    def test_frame_add_and_base_image_change_are_separate_undo_steps(self, tmp_path):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        frame_path = tmp_path / "frame.png"
        base_path = tmp_path / "base.png"
        project_file.write_text(json.dumps({"Project Name": "Project"}), encoding="utf-8")
        frame_path.write_text("frame", encoding="utf-8")
        base_path.write_text("base", encoding="utf-8")
        sprite_path.write_text(
            json.dumps(
                {
                    "uuid": "sprite-1",
                    "name": "Hero",
                    "description": "",
                    "width": 32,
                    "height": 32,
                    "base_image": "",
                    "include_base_image_in_animations": True,
                    "animations": {"idle": []},
                }
            ),
            encoding="utf-8",
        )
        cast(Any, self.view.base_image_loader).get_absolute_path = lambda: (
            self.dummy_loader.loaded[-1] if self.dummy_loader.loaded else ""
        )
        sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )

        self.view.load_sprite_data(str(sprite_path), sage_file)
        self.view._insert_frames_at_index([str(frame_path)], 0)
        self.dummy_loader.load_image(str(base_path))
        self.view._on_base_image_selected(str(base_path))

        state = self.view.undo_redo_state()
        assert state.undo_count == 2
        assert state.undo_text == "Change base image"

        self.view.undo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == ""
        assert self.view.sprite_data.get_animation_frames("idle") == [str(frame_path)]

        self.view.undo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == ""
        assert self.view.sprite_data.get_animation_frames("idle") == []

        self.view.redo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == ""
        assert self.view.sprite_data.get_animation_frames("idle") == [str(frame_path)]

        self.view.redo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == str(base_path)
        assert self.view.sprite_data.get_animation_frames("idle") == [str(frame_path)]

    def test_frame_move_and_remove_remain_undoable(self, tmp_path):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        frame_a = tmp_path / "a.png"
        frame_b = tmp_path / "b.png"
        frame_c = tmp_path / "c.png"
        project_file.write_text(json.dumps({"Project Name": "Project"}), encoding="utf-8")
        for frame_path in (frame_a, frame_b, frame_c):
            frame_path.write_text("frame", encoding="utf-8")
        sprite_path.write_text(
            json.dumps(
                {
                    "uuid": "sprite-1",
                    "name": "Hero",
                    "description": "",
                    "width": 32,
                    "height": 32,
                    "base_image": "",
                    "include_base_image_in_animations": True,
                    "animations": {"idle": ["a.png", "b.png", "c.png"]},
                }
            ),
            encoding="utf-8",
        )
        cast(Any, self.view.base_image_loader).get_absolute_path = lambda: ""
        sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )

        self.view.load_sprite_data(str(sprite_path), sage_file)
        self.view.frame_list_widget.setCurrentRow(1)
        self.view._move_frame_down()

        assert self.view.sprite_data is not None
        assert self.view.sprite_data.get_animation_frames("idle") == [
            str(frame_a),
            str(frame_c),
            str(frame_b),
        ]
        assert self.view.undo_redo_state().undo_text == "Move frame"

        self.view.undo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.get_animation_frames("idle") == [
            str(frame_a),
            str(frame_b),
            str(frame_c),
        ]

        self.view.redo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.get_animation_frames("idle") == [
            str(frame_a),
            str(frame_c),
            str(frame_b),
        ]

        self.view.frame_list_widget.setCurrentRow(1)
        self.view._remove_frame()

        assert self.view.sprite_data is not None
        assert self.view.sprite_data.get_animation_frames("idle") == [str(frame_a), str(frame_b)]
        assert self.view.undo_redo_state().undo_text == "Remove frame"

        self.view.undo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.get_animation_frames("idle") == [
            str(frame_a),
            str(frame_c),
            str(frame_b),
        ]

    def test_clearing_base_image_is_undoable(self, tmp_path):
        project_file = tmp_path / "project.sage"
        sprite_path = tmp_path / "hero.sprite"
        base_path = tmp_path / "base.png"
        project_file.write_text(json.dumps({"Project Name": "Project"}), encoding="utf-8")
        base_path.write_text("base", encoding="utf-8")
        sprite_path.write_text(
            json.dumps(
                {
                    "uuid": "sprite-1",
                    "name": "Hero",
                    "description": "",
                    "width": 32,
                    "height": 32,
                    "base_image": "base.png",
                    "include_base_image_in_animations": True,
                    "animations": {},
                }
            ),
            encoding="utf-8",
        )
        cast(Any, self.view.base_image_loader).get_absolute_path = lambda: ""
        sage_file = SageFile(
            project_name="Project",
            version="1.0",
            created_at="2026-01-01T00:00:00",
            project_description="",
            keywords="",
            camera="",
            reference_images=[],
            last_saved="",
            filepath=str(project_file),
        )

        self.view.load_sprite_data(str(sprite_path), sage_file)
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == str(base_path)

        self.view._on_base_image_selected("")

        state = self.view.undo_redo_state()
        assert state.can_undo
        assert state.undo_text == "Clear base image"
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == ""

        self.view.undo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == str(base_path)
        assert self.view.undo_redo_state().can_redo

        self.view.redo()
        assert self.view.sprite_data is not None
        assert self.view.sprite_data.base_image == ""

    def test_load_sprite_data_success(self, tmp_path, monkeypatch):
        # Prepare a valid sprite “JSON”—but we will not actually parse it. Instead, stub out from_json().
        sample = {
            "name": "Hero",
            "description": "Brave warrior",
            "width": 32,
            "height": 48,
            "base_image": "hero.png",
            "animations": {"idle": [], "walk": ["step1.png", "step2.png"]},
        }
        spr_file = tmp_path / "sprite.spr"
        spr_file.write_text(json.dumps(sample), encoding="utf-8")

        # Create the base_image on disk so load_image won't error
        (tmp_path / "hero.png").write_text("dummy")

        # Build a dummy object that mimics SpriteFile with exactly the attributes/views that load_sprite_data expects:
        class DummySprite:
            def __init__(self, data, base_dir):
                # Echo back fields into attributes:
                self.name = data["name"]
                self.description = data["description"]
                self.width = data["width"]
                self.height = data["height"]
                self.base_image = data["base_image"]
                # animations is a dict of lists
                self.animations = data["animations"]

            def get_animation_frames(self, animation_name):
                return self.animations.get(animation_name, [])

        # Monkeypatch SpriteFile.from_json so that it returns our dummy, instead of real parsing
        monkeypatch.setattr(
            sprite_editor.SpriteFile,
            "from_json",
            lambda fpath, sage_directory: DummySprite(sample, str(tmp_path)),
        )

        # Spy on load_image
        loaded = []
        monkeypatch.setattr(
            self.view.base_image_loader, "load_image", lambda path: loaded.append(path)
        )

        # The base_image_loader already has blockSignals and clear_image stubbed in setup_view

        # Call load_sprite_data
        self.view.load_sprite_data(str(spr_file), self.sage_file)

        # UI fields populated
        assert self.view.name_edit.text() == "Hero"
        assert self.view.desc_edit.toPlainText() == "Brave warrior"
        assert self.view.width_spin.value() == 32
        assert self.view.height_spin.value() == 48
        assert self.view.include_base_image_check.isChecked()

        # Base-dir set correctly and load_image called for base_image
        assert self.view.base_image_loader.base_dir == str(tmp_path)
        assert loaded == ["hero.png"]

        # Animations loaded (sorted keys: ['idle', 'walk'])
        loaded_names = [
            self.view.anim_list_widget.item(i).text()
            for i in range(self.view.anim_list_widget.count())
        ]
        assert loaded_names == ["idle", "walk"]

    def test_include_base_image_toggle_updates_sprite_and_preview(self, monkeypatch):
        class DummySprite:
            include_base_image_in_animations = True

        sprite = DummySprite()
        cast(Any, self.view).sprite_data = sprite
        preview_updates = []
        saves = []
        monkeypatch.setattr(
            self.view,
            "_update_animation_preview",
            lambda: preview_updates.append(True),
        )
        monkeypatch.setattr(self.view, "save", lambda *args, **kwargs: saves.append(kwargs))

        self.view._on_include_base_image_in_animations_toggled(False)

        assert sprite.include_base_image_in_animations is False
        assert preview_updates == [True]
        assert saves and saves[0]["label"] == "Toggle base image in animations"

    def test_load_sprite_data_invalid_json(self, tmp_path, monkeypatch):
        # Write invalid JSON
        bad_file = tmp_path / "bad.spr"
        bad_file.write_text("{ not valid json")

        # Stub SpriteFile.from_json to raise
        monkeypatch.setattr(
            sprite_editor.SpriteFile,
            "from_json",
            lambda fpath, sage_directory: (_ for _ in ()).throw(Exception("parse failure")),
        )

        # Spy on the critical error dialog
        called = {}

        def fake_critical(selfwin, title, text):
            called["critical"] = (title, text)

        monkeypatch.setattr(QtWidgets.QMessageBox, "critical", fake_critical)

        # Call load
        self.view.load_sprite_data(str(bad_file), self.sage_file)

        # Error branch must fire
        assert "critical" in called
        # state reset
        assert self.view.current_file_path is None
        assert self.view._base_dir is None
        assert self.view.sprite_data is None


# (Note: We have removed the “

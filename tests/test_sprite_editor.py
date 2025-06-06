import os
import json
import tempfile
import pytest

from PySide6 import QtWidgets, QtCore, QtGui

import sprite_editor
from sprite_editor import AnimationPreviewWidget, SpriteEditorView
from sage_editor import SageFile
import config


@pytest.fixture(scope='session', autouse=True)
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
        w.load_animation(['a.png'], base_dir='nonexistent_dir')
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
        w.load_animation(['missing.png'], base_dir=tmp)
        out = capsys.readouterr().out
        assert "Frame image not found" in out
        # label should indicate could not load any frames
        assert "Could not load" in w.image_label.text()
        assert not w.pixmaps

    def test_load_animation_single_frame(self, tmp_path):
        w = self.widget
        # create a small image
        img_path = tmp_path / 'f.png'
        pix = QtGui.QPixmap(20, 20)
        pix.fill(QtCore.Qt.red)
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
        for i, color in enumerate([QtCore.Qt.blue, QtCore.Qt.green]):
            img = tmp_path / f'{i}.png'
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
        w.image_label.setText('Temp')
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
        open(file_path, 'w').write('{}')
        # Add dummy camera argument, to match SageFile.__init__ signature
        self.sage_file = SageFile(
            project_name='p',
            version='v',
            created_at='c',
            project_description='pd',
            keywords='kw',
            camera='dummy_camera',
            reference_images=[],
            last_saved='ls',
            filepath=file_path
        )

        # Instantiate view
        self.view = SpriteEditorView(config.APP_PALETTE)
        # Inject sage_file and current_file_path
        self.view.sage_file = self.sage_file
        self.view.current_file_path = file_path
        self.view._base_dir = str(self.tmp_dir)

        # Stub base_image_loader
        class DummyLoader:
            def __init__(s):
                s.loaded = []

            def load_image(s, path):
                s.loaded.append(path)

            def get_relative_path(s):
                return s.loaded[-1] if s.loaded else None

            def blockSignals(s, block):
                pass

            def clear_image(s, emit_signal=False):
                pass

        self.dummy_loader = DummyLoader()
        self.view.base_image_loader = self.dummy_loader
        return self.view

    def test_on_base_image_action_clicked_no_desc(self, monkeypatch, capsys):
        v = self.view
        # Ensure desc is empty
        v.desc_edit.setPlainText('')
        # Monkeypatch QMessageBox.warning
        called = {}

        def fake_warning(selfwin, title, text):
            called['warn'] = (title, text)

        monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', fake_warning)
        # Call method
        v._on_base_image_action_clicked(index=0)
        # Should warn and abort
        assert 'warn' in called
        out = capsys.readouterr().out
        assert "AI generation aborted" in out
        # Loader not called
        assert not self.dummy_loader.loaded

    def test_on_base_image_action_clicked_ai_none(self, monkeypatch, capsys):
        v = self.view
        # Set description
        v.desc_edit.setPlainText('desc')

        # Dummy AIModelManager with get_active_vendor()
        class DummyVendor:
            def __init__(self, value):
                self.value = value

        class DummyMM:
            def generate_base_sprite_image(self, **kwargs):
                return None

            def get_active_vendor(self):
                return DummyVendor("dummy_vendor")

        monkeypatch.setattr(sprite_editor, 'AIModelManager', lambda: DummyMM())
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
        v.desc_edit.setPlainText('d')

        # Create fake AI image
        ai_img = tmp_path / 'gen.png'
        pix = QtGui.QPixmap(10, 10)
        pix.fill(QtCore.Qt.black)
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

        monkeypatch.setattr(sprite_editor, 'AIModelManager', lambda: DummyMM())

        # Provide a dummy sprite_data object that has a base_image attribute
        class DummySprite:
            pass

        v.sprite_data = DummySprite()

        # Stub save() so we can verify it gets called
        calls = []
        v.save = lambda: calls.append(True)

        # Call method
        v._on_base_image_action_clicked(index=2)
        out = capsys.readouterr().out

        # Loader called
        assert self.dummy_loader.loaded and self.dummy_loader.loaded[0] == str(ai_img)

        # save() called
        assert calls

        # Final log printed
        assert "triggered AIModelManager" in out

    def test_set_animation_controls_enabled(self, monkeypatch):
        v = self.view
        # Stub update_frame_button_states
        called = []
        monkeypatch.setattr(v, '_update_frame_button_states', lambda: called.append(True))
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
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(self._text)

        dummy_data = DummySpriteData('{"x":1}')
        v.sprite_data = dummy_data

        # Provide a dummy undo_redo_manager with a no-op save_undo_state
        v._undo_redo_manager = type("U", (), {"save_undo_state": lambda self, prev: None})()

        # Point current_file_path to tmp
        fp = tmp_path / 'out.spr'
        v.current_file_path = str(fp)

        # Override _get_sprite_data_to_save to return our dummy
        v._get_sprite_data_to_save = lambda: dummy_data

        # Call save()
        v.save()

        # File written
        assert fp.exists()
        assert fp.read_text(encoding='utf-8') == '{"x":1}'

    def test_load_sprite_data_success(self, tmp_path, monkeypatch):
        # Prepare a valid sprite “JSON”—but we will not actually parse it. Instead, stub out from_json().
        sample = {
            "name": "Hero",
            "description": "Brave warrior",
            "width": 32,
            "height": 48,
            "base_image": "hero.png",
            "animations": {
                "idle": [],
                "walk": ["step1.png", "step2.png"]
            }
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
            lambda fpath, sage_directory: DummySprite(sample, str(tmp_path))
        )

        # Spy on load_image
        loaded = []
        monkeypatch.setattr(
            self.view.base_image_loader,
            "load_image",
            lambda path: loaded.append(path)
        )

        # The base_image_loader already has blockSignals and clear_image stubbed in setup_view

        # Call load_sprite_data
        self.view.load_sprite_data(str(spr_file), self.sage_file)

        # UI fields populated
        assert self.view.name_edit.text() == "Hero"
        assert self.view.desc_edit.toPlainText() == "Brave warrior"
        assert self.view.width_spin.value() == 32
        assert self.view.height_spin.value() == 48

        # Base-dir set correctly and load_image called for base_image
        assert self.view.base_image_loader.base_dir == str(tmp_path)
        assert loaded == ["hero.png"]

        # Animations loaded (sorted keys: ['idle', 'walk'])
        loaded_names = [self.view.anim_list_widget.item(i).text() for i in range(self.view.anim_list_widget.count())]
        assert loaded_names == ["idle", "walk"]

    def test_load_sprite_data_invalid_json(self, tmp_path, monkeypatch):
        # Write invalid JSON
        bad_file = tmp_path / "bad.spr"
        bad_file.write_text("{ not valid json")

        # Stub SpriteFile.from_json to raise
        monkeypatch.setattr(
            sprite_editor.SpriteFile,
            "from_json",
            lambda fpath, sage_directory: (_ for _ in ()).throw(Exception("parse failure"))
        )

        # Spy on the critical error dialog
        called = {}

        def fake_critical(selfwin, title, text):
            called['critical'] = (title, text)

        monkeypatch.setattr(QtWidgets.QMessageBox, "critical", fake_critical)

        # Call load
        self.view.load_sprite_data(str(bad_file), self.sage_file)

        # Error branch must fire
        assert 'critical' in called
        # state reset
        assert self.view.current_file_path is None
        assert self.view._base_dir is None
        assert self.view.sprite_data is None


# (Note: We have removed the “

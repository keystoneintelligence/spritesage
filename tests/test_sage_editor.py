import os
import re
import json
import tempfile
from types import SimpleNamespace
import pytest

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from spritesage import sage_editor
from spritesage.sage_editor import SageFile, SageEditorView
from spritesage.model_baker import ModelBakeConfig
from spritesage.model_baker.dialog import ModelBakeDialog
from spritesage import config


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture(autouse=True)
def patch_image_loader_and_icon(monkeypatch):
    # Dummy signal class to simulate Qt signals
    class DummySignal:
        def __init__(self):
            self._handlers = []

        def connect(self, handler):
            self._handlers.append(handler)

        def emit(self, *args, **kwargs):
            for h in self._handlers:
                h(*args, **kwargs)

    class DummyLoader(QtWidgets.QWidget):
        def __init__(self, directory, palette, index, parent=None):
            super().__init__(parent)
            self.directory = directory
            self.palette = palette
            self.index = index
            self._relative = None
            self.image_updated = DummySignal()
            self.action_clicked = DummySignal()

        def load_image(self, path):
            # Simulate loading and set relative path
            self._relative = path
            return True

        # Accept an optional sage_dir argument to match code
        def get_relative_path(self, sage_dir=None):
            return self._relative

    class DummyIconButton(QtWidgets.QWidget):
        def __init__(self, palette, action_string, tooltip, parent=None):
            super().__init__(parent)
            self.palette = palette
            self.action_string = action_string
            self.tooltip = tooltip
            self.clicked_with_action = DummySignal()

    monkeypatch.setattr(sage_editor, "ImageLoaderWidget", DummyLoader)
    monkeypatch.setattr(sage_editor, "ActionIconButton", DummyIconButton)
    return DummyLoader, DummyIconButton


class TestSageFile:
    def test_from_json_to_dict_directory(self, tmp_path):
        data = {
            "Project Name": "TestProj",
            "version": "1.0",
            "createdAt": "2025-01-01T00:00:00",
            "Project Description": "Desc",
            "Keywords": "kw1,kw2",
            "Reference Images": ["img1.png", "img2.png"],
            "lastSaved": "2025-01-02T00:00:00",
        }
        fp = tmp_path / "test.sage"
        fp.write_text(json.dumps(data), encoding="utf-8")
        sf = SageFile.from_json(str(fp))
        # The code stores reference_images as absolute paths
        expected_paths = [
            os.path.join(str(tmp_path), "img1.png"),
            os.path.join(str(tmp_path), "img2.png"),
        ]
        assert sf.project_name == data["Project Name"]
        assert sf.version == data["version"]
        assert sf.created_at == data["createdAt"]
        assert sf.project_description == data["Project Description"]
        assert sf.keywords == data["Keywords"]
        assert sf.reference_images == expected_paths
        assert sf.last_saved == data["lastSaved"]
        assert sf.filepath == str(fp)

        # to_dict should reconstruct the original JSON structure, plus "Camera":""
        d = sf.to_dict()
        expected = data.copy()
        expected["Camera"] = ""
        assert d == expected

        # directory property
        assert sf.directory == str(tmp_path)

    def test_update_last_saved(self):
        # Provide all 9 arguments: project_name, version, created_at, project_description, keywords, camera, reference_images, last_saved, filepath
        sf = SageFile("n", "v", "c", "d", "k", "cam", [], "old", "f.sage")
        sf.update_last_saved()
        # ISO format YYYY-MM-DDTHH:MM:SS
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", sf.last_saved)

    def test_save_writes_file(self, tmp_path):
        fp = tmp_path / "out.sage"
        sf = SageFile("n", "v", "c", "d", "k", "cam", [], "old", str(fp))
        sf.save()
        # file exists
        assert fp.exists()
        loaded = json.loads(fp.read_text(encoding="utf-8"))
        # Must contain saved fields
        assert loaded["Project Name"] == "n"
        assert "lastSaved" in loaded

    def test_reference_image_abs_paths(self, tmp_path, capsys):
        # Create dummy image files
        dirp = tmp_path / "prj"
        dirp.mkdir()
        img1 = dirp / "a.png"
        img2 = dirp / "b.png"
        img1.write_text("")
        img2.write_text("")

        # Note: include camera argument
        sf = SageFile(
            "n",
            "v",
            "c",
            "d",
            "k",
            "cam",
            ["a.png", "missing.png", "b.png"],
            "ls",
            str(dirp / "f.sage"),
        )
        paths = sf.reference_image_abs_paths()
        # Should include existing a.png and b.png
        assert str(img1) in paths
        assert str(img2) in paths
        # excluding index 0 (a.png)
        paths2 = sf.reference_image_abs_paths(exclude_index=0)
        assert str(img1) not in paths2


class TestSageEditorView:
    @pytest.fixture(autouse=True)
    def setup_view(self, patch_image_loader_and_icon):
        self.palette = config.APP_PALETTE
        self.DummyLoader, self.DummyIconButton = patch_image_loader_and_icon
        self.view = SageEditorView(self.palette)
        return self.view

    def test_instantiation(self):
        view = self.view
        assert view.app_palette == config.APP_PALETTE
        assert isinstance(view.scroll_area, QtWidgets.QScrollArea)
        assert isinstance(view.content_widget, QtWidgets.QWidget)
        assert isinstance(view.form_layout, QtWidgets.QFormLayout)
        assert view.sage_file is None

    def test_create_sprite_buttons(self):
        btns = self.view._create_sprite_buttons()
        qt_btns = btns.findChildren(QtWidgets.QPushButton)
        texts = [b.text() for b in qt_btns]
        assert "New Sprite" in texts
        assert "Import 3D Model..." in texts

    def test_model_bake_dialog_builds_config(self, tmp_path):
        model_path = tmp_path / "bandit.glb"
        model_path.write_bytes(b"placeholder")

        dialog = ModelBakeDialog(tmp_path, self.palette)
        dialog.model_path_edit.setText(str(model_path))
        dialog._model_path_changed()
        dialog.view_set_combo.setCurrentText("side2")
        dialog.fps_spin.setValue(12.0)
        dialog.size_spin.setValue(128)
        dialog.zoom_spin.setValue(1.5)
        dialog.max_frames_check.setChecked(True)
        dialog.max_frames_spin.setValue(3)

        bake_config = dialog.to_config()

        assert bake_config.model_path == model_path
        assert bake_config.project_dir == tmp_path
        assert bake_config.sprite_name == "bandit"
        assert bake_config.view_set == "side2"
        assert bake_config.fps == 12.0
        assert bake_config.frame_size == 128
        assert bake_config.zoom == 1.5
        assert bake_config.max_frames == 3

    def test_model_bake_dialog_all_checked_animations_means_bake_all(self, tmp_path):
        dialog = ModelBakeDialog(tmp_path, self.palette)
        for name in ("Walking", "Running"):
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, name)
            dialog.animation_list.addItem(item)

        assert dialog.selected_animations() is None
        assert dialog._selected_animation_count() == 2

    def test_create_and_populate_sprite_table(self, tmp_path, monkeypatch, capsys):
        # Create dummy .sprite files in two nested directories
        dirp = tmp_path / "dir"
        dirp.mkdir()
        f1 = dirp / "one.sprite"
        f2dir = dirp / "sub"
        f2dir.mkdir()
        f2 = f2dir / "two.sprite"
        f1.write_text("")
        f2.write_text("")
        # Dummy SageFile pointing here (camera and empty ref_images)
        sf = SageFile(
            "n", "v", "c", "d", "k", "cam", [], "ls", str(dirp / "f.sage")  # reference_images
        )
        table = self.view._create_sprite_table()
        self.view.sage_file = sf
        self.view._populate_sprite_table(table)
        # Expect 2 rows for the two .sprite files
        assert table.rowCount() == 2
        items = []
        for i in range(table.rowCount()):
            item = table.item(i, 0)
            assert item is not None
            items.append(item.text())
        items = sorted(items)
        assert "one.sprite" in items
        assert "sub/two.sprite" in items

    def test_import_model_button_bakes_refreshes_and_opens_sprite(self, tmp_path, monkeypatch):
        sage_path = tmp_path / "project.sage"
        sf = SageFile("n", "v", "c", "d", "k", "cam", [], "ls", str(sage_path))
        model_path = tmp_path / "bandit.glb"
        model_path.write_bytes(b"placeholder")
        sprite_path = tmp_path / "Bandit.sprite"
        self.view.sage_file = sf
        self.view._widgets = {self.view.SPRITE_TABLE_KEY: self.view._create_sprite_table()}

        class FakeDialog:
            def __init__(self, project_dir, palette, parent=None):
                self.project_dir = project_dir
                self.palette = palette
                self.parent = parent

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def to_config(self):
                return ModelBakeConfig(
                    model_path=model_path,
                    project_dir=tmp_path,
                    sprite_name="Bandit",
                    max_frames=1,
                )

        def fake_call_with_busy(parent, fn, *args, **kwargs):
            return fn()

        def fake_bake_model_to_sprite_project(bake_config):
            assert bake_config.model_path == model_path
            sprite_path.write_text(
                json.dumps(
                    {
                        "uuid": "test",
                        "name": "Bandit",
                        "description": "",
                        "width": 64,
                        "height": 64,
                        "base_image": None,
                        "animations": {},
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                sprite_path=sprite_path,
                frame_count=2,
                animation_names=("Walking_front",),
            )

        completed = []
        opened = []
        monkeypatch.setattr(sage_editor, "ModelBakeDialog", FakeDialog)
        monkeypatch.setattr(sage_editor, "call_with_busy", fake_call_with_busy)
        monkeypatch.setattr(
            sage_editor,
            "bake_model_to_sprite_project",
            fake_bake_model_to_sprite_project,
        )
        monkeypatch.setattr(self.view, "_show_model_bake_complete", completed.append)
        self.view.sprite_row_action.connect(opened.append)

        self.view._import_model_button_clicked()

        table = self.view._widgets[self.view.SPRITE_TABLE_KEY]
        assert table.rowCount() == 1
        sprite_item = table.item(0, 0)
        assert sprite_item is not None
        assert sprite_item.text() == "Bandit.sprite"
        assert completed[0].sprite_path == sprite_path
        assert opened == [str(sprite_path)]

    def test_export_folder_dialog_uses_readable_palette(self):
        dialog = self.view._create_export_folder_dialog("hero_godot_export")
        label = dialog.findChild(QtWidgets.QLabel)
        line_edit = dialog.lineEdit()

        stylesheet = dialog.styleSheet()
        assert dialog.windowTitle() == "Godot Export Folder"
        assert dialog.textValue() == "hero_godot_export"
        assert label is not None
        assert label.text() == "Folder name:"
        assert line_edit is not None
        assert line_edit.text() == "hero_godot_export"
        assert "QDialog#SpriteSagePopupDialog QLabel" in stylesheet
        assert label.property("dialogTextPanel") is None
        assert config.APP_PALETTE["editable_value_bg"] in line_edit.styleSheet()
        assert config.APP_PALETTE["text_color"] in line_edit.styleSheet()

    def test_export_sprite_to_godot_writes_under_exports_folder(self, monkeypatch, tmp_path):
        project_file = tmp_path / "project.sage"
        self.view.sage_file = SageFile(
            "Project",
            "1.0",
            "2026-01-01T00:00:00",
            "",
            "",
            "",
            [],
            "",
            str(project_file),
        )
        sprite_path = tmp_path / "hero.sprite"
        sprite_path.write_text("{}", encoding="utf-8")
        parsed_sprite = object()
        exporter_calls = []
        completed = []
        progress_callback = object()

        class FakeExporter:
            def __init__(self, sprite_file, output_dir, progress_callback=None):
                exporter_calls.append((sprite_file, output_dir, progress_callback))

            def export(self):
                return None

        def fake_call_with_progress(parent, fn, *args, **kwargs):
            assert parent is self.view
            assert kwargs["progress_label"] == "Exporting Godot sprite"
            return fn(progress_callback=progress_callback)

        def fake_from_json(fpath, sage_directory):
            assert fpath == str(sprite_path)
            assert sage_directory == str(tmp_path)
            return parsed_sprite

        monkeypatch.setattr(
            self.view, "_prompt_for_export_folder_name", lambda default: ("hero", True)
        )
        monkeypatch.setattr(sage_editor.SpriteFile, "from_json", fake_from_json)
        monkeypatch.setattr(sage_editor, "GodotSpriteExporter", FakeExporter)
        monkeypatch.setattr(sage_editor, "call_with_progress", fake_call_with_progress)
        monkeypatch.setattr(
            self.view,
            "_show_export_complete",
            lambda path, output: completed.append((path, output)),
        )

        self.view._export_sprite_to_godot("hero.sprite")

        expected_output_dir = os.path.join(str(tmp_path), "exports", "hero")
        assert exporter_calls == [(parsed_sprite, expected_output_dir, progress_callback)]
        assert completed == [("hero.sprite", expected_output_dir)]

    def test_export_project_to_godot_writes_under_exports_folder(self, monkeypatch, tmp_path):
        project_file = tmp_path / "project.sage"
        self.view.sage_file = SageFile(
            "Project",
            "1.0",
            "2026-01-01T00:00:00",
            "",
            "",
            "",
            [],
            "",
            str(project_file),
        )
        exporter_calls = []
        completed = []
        progress_callback = object()

        class FakeProjectExporter:
            def __init__(self, project_dir, output_dir, progress_callback=None):
                exporter_calls.append((project_dir, output_dir, progress_callback))

            def export(self):
                return [object(), object()]

        def fake_call_with_progress(parent, fn, *args, **kwargs):
            assert parent is self.view
            assert kwargs["progress_label"] == "Exporting Godot project"
            assert kwargs["progress_unit"] == "sprites"
            return fn(progress_callback=progress_callback)

        monkeypatch.setattr(
            self.view, "_prompt_for_export_folder_name", lambda default: ("project", True)
        )
        monkeypatch.setattr(sage_editor, "GodotProjectExporter", FakeProjectExporter)
        monkeypatch.setattr(sage_editor, "call_with_progress", fake_call_with_progress)
        monkeypatch.setattr(
            self.view,
            "_show_project_export_complete",
            lambda output, count: completed.append((output, count)),
        )

        self.view._export_project_to_godot()

        expected_output_dir = os.path.join(str(tmp_path), "exports", "project")
        assert exporter_calls == [(str(tmp_path), expected_output_dir, progress_callback)]
        assert completed == [(expected_output_dir, 2)]

    def test_export_complete_message_uses_readable_palette(self, monkeypatch):
        created_boxes = []

        class FakeMessageBox:
            class Icon:
                Information = "information"
                Critical = "critical"

            class StandardButton:
                Ok = "ok"

            def __init__(self, parent=None):
                self.parent = parent
                self.icon = None
                self.title = ""
                self.text = ""
                self.buttons = None
                self.stylesheet = ""
                self.executed = False
                created_boxes.append(self)

            def setIcon(self, icon):
                self.icon = icon

            def setWindowTitle(self, title):
                self.title = title

            def setText(self, text):
                self.text = text

            def setStandardButtons(self, buttons):
                self.buttons = buttons

            def setStyleSheet(self, stylesheet):
                self.stylesheet = stylesheet

            def exec(self):
                self.executed = True

        monkeypatch.setattr(sage_editor, "QMessageBox", FakeMessageBox)

        self.view._show_export_complete("hero.sprite", "C:/project/hero_godot_export")

        assert len(created_boxes) == 1
        box = created_boxes[0]
        assert box.parent is self.view
        assert box.icon == FakeMessageBox.Icon.Information
        assert box.title == "Export Complete"
        assert "hero.sprite" in box.text
        assert "QMessageBox QLabel" in box.stylesheet
        assert f"background-color: {config.APP_PALETTE['dialog_bg']};" in box.stylesheet
        assert f"color: {config.APP_PALETTE['text_color']};" in box.stylesheet
        assert box.buttons == FakeMessageBox.StandardButton.Ok
        assert box.executed

    def test_on_text_and_image_signals(self, tmp_path):
        view = self.view
        # Prepare a minimal SageFile so save() does not crash
        fp = tmp_path / "t.sage"
        sf = SageFile("PN", "ver", "ca", "pd", "kw", "cam", [], "ls", str(fp))
        view.sage_file = sf

        # Call the internal slot; it should write a file
        view._on_text_field_changed("any_key", "some_text")
        assert fp.exists()

        # Prepare an image path in the same directory to test image_updated slot
        img = tmp_path / "some.png"
        img.write_text("")
        sf.reference_images = [str(img)]
        view.sage_file = sf
        # Should not raise once reference_images stores an absolute path
        view._on_image_updated("Reference Images", 0, str(img))
        assert fp.exists()

    def test_common_icon_button_clicked_for_sage(self, monkeypatch, capsys, tmp_path):
        # Stub AIModelManager to accept a single 'input' argument and return fixed strings
        class DummyMM:
            def generate_project_description(self, input):
                return "ND"

            def generate_keywords(self, input):
                return "NK"

            def get_active_vendor(self):
                class V:
                    value = "DummyVendor"

                return V()

        monkeypatch.setattr(sage_editor, "AIModelManager", DummyMM)

        view = self.view
        # Prepare QLineEdits for Project Description and Keywords
        pd = QtWidgets.QLineEdit()
        pd.setText("old")
        kw = QtWidgets.QLineEdit()
        kw.setText("old2")
        view._widgets = {"Project Description": pd, "Keywords": kw}

        # Dummy SageFile with valid directory (camera and empty ref_images)
        d = tempfile.mkdtemp()
        sf = SageFile(
            "n", "v", "c", "d", "k", "cam", [], "ls", os.path.join(d, "f.sage")  # reference_images
        )
        sf.reference_images = []  # no images for context
        view.sage_file = sf

        # Test description-generation action
        view._common_icon_button_clicked_for_sage("TEXT_FIELD_ACTION_Project_Description")
        assert pd.text() == "ND"

        # Test keywords-generation action
        view._common_icon_button_clicked_for_sage("TEXT_FIELD_ACTION_Keywords")
        assert kw.text() == "NK"

    def test_get_edited_data_basic(self):
        # Prepare SageFile with initial data
        sf = SageFile(
            "PN",
            "ver",
            "ca",
            "pd",
            "kw",
            "cam",
            ["a", "b"],  # reference_images
            "ls",
            "/tmp/x.sage",
        )
        view = self.view
        view.sage_file = sf

        # Prepare widgets for Project Description and Keywords
        pd = QtWidgets.QLineEdit()
        pd.setText("newpd")
        kw = QtWidgets.QLineEdit()
        kw.setText("newkw")

        # Dummy loaders for 4 entries with relative paths
        loaders = []
        for i in range(4):
            loader = self.DummyLoader("/d", self.palette, i)
            loader._relative = ["a", "b", "", ""][i]
            loaders.append(loader)

        view._widgets = {
            "Project Description": pd,
            "Keywords": kw,
            SageEditorView.REFERENCE_IMAGES_KEY: loaders,
        }

        modified = view.get_modified_sage_file().to_dict()
        assert modified["Project Description"] == "newpd"
        assert modified["Keywords"] == "newkw"
        # The code will treat empty string as ".", so expect that
        assert modified["Reference Images"] == ["a", "b", ".", "."]

        # Hidden and locked fields must be preserved
        assert modified["Project Name"] == "PN"
        assert modified["version"] == "ver"
        assert modified["createdAt"] == "ca"
        assert modified["lastSaved"] == "ls"

    def test_save_functionality(self, tmp_path):
        view = self.view
        fp = tmp_path / "t.sage"
        # Create a SageFile and assign to view
        sf = SageFile("PN", "ver", "ca", "pd", "kw", "cam", [], "ls", str(fp))
        view.sage_file = sf

        # Prepare a Project Description widget to modify data
        pd = QtWidgets.QLineEdit()
        pd.setText("updated")
        view._widgets = {"Project Description": pd}

        # Call save, which should write to the filepath
        view.save()
        loaded = json.loads(fp.read_text(encoding="utf-8"))
        assert loaded["Project Description"] == "updated"

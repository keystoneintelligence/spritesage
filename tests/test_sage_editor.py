import os
import re
import json
import tempfile
import pytest

from PySide6 import QtWidgets

import sage_editor
from sage_editor import SageFile, SageEditorView
import config

@pytest.fixture(scope='session', autouse=True)
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

    monkeypatch.setattr(sage_editor, 'ImageLoaderWidget', DummyLoader)
    monkeypatch.setattr(sage_editor, 'ActionIconButton', DummyIconButton)
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
            "lastSaved": "2025-01-02T00:00:00"
        }
        fp = tmp_path / "test.sage"
        fp.write_text(json.dumps(data), encoding='utf-8')
        sf = SageFile.from_json(str(fp))
        # The code stores reference_images as absolute paths
        expected_paths = [
            os.path.join(str(tmp_path), "img1.png"),
            os.path.join(str(tmp_path), "img2.png")
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
        sf = SageFile('n', 'v', 'c', 'd', 'k', 'cam', [], 'old', 'f.sage')
        sf.update_last_saved()
        # ISO format YYYY-MM-DDTHH:MM:SS
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", sf.last_saved)

    def test_save_writes_file(self, tmp_path):
        fp = tmp_path / "out.sage"
        sf = SageFile('n', 'v', 'c', 'd', 'k', 'cam', [], 'old', str(fp))
        sf.save()
        # file exists
        assert fp.exists()
        loaded = json.loads(fp.read_text(encoding='utf-8'))
        # Must contain saved fields
        assert loaded["Project Name"] == 'n'
        assert "lastSaved" in loaded

    def test_reference_image_abs_paths(self, tmp_path, capsys):
        # Create dummy image files
        dirp = tmp_path / "prj"
        dirp.mkdir()
        img1 = dirp / "a.png"
        img2 = dirp / "b.png"
        img1.write_text('')
        img2.write_text('')

        # Note: include camera argument
        sf = SageFile(
            'n', 'v', 'c', 'd', 'k', 'cam',
            ['a.png', 'missing.png', 'b.png'],
            'ls',
            str(dirp / 'f.sage')
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
        assert view.palette == config.APP_PALETTE
        assert isinstance(view.scroll_area, QtWidgets.QScrollArea)
        assert isinstance(view.content_widget, QtWidgets.QWidget)
        assert isinstance(view.form_layout, QtWidgets.QFormLayout)
        assert view.sage_file is None

    def test_create_sprite_buttons(self):
        btns = self.view._create_sprite_buttons()
        qt_btns = btns.findChildren(QtWidgets.QPushButton)
        texts = [b.text() for b in qt_btns]
        assert "New Sprite" in texts

    def test_create_and_populate_sprite_table(self, tmp_path, monkeypatch, capsys):
        # Create dummy .sprite files in two nested directories
        dirp = tmp_path / "dir"
        dirp.mkdir()
        f1 = dirp / 'one.sprite'
        f2dir = dirp / 'sub'
        f2dir.mkdir()
        f2 = f2dir / 'two.sprite'
        f1.write_text('')
        f2.write_text('')
        # Dummy SageFile pointing here (camera and empty ref_images)
        sf = SageFile(
            'n', 'v', 'c', 'd', 'k', 'cam',
            [],  # reference_images
            'ls',
            str(dirp / 'f.sage')
        )
        table = self.view._create_sprite_table()
        self.view.sage_file = sf
        self.view._populate_sprite_table(table)
        # Expect 2 rows for the two .sprite files
        assert table.rowCount() == 2
        items = sorted([table.item(i, 0).text() for i in range(table.rowCount())])
        assert 'one.sprite' in items
        assert 'sub/two.sprite' in items

    def test_on_text_and_image_signals(self, tmp_path):
        view = self.view
        # Prepare a minimal SageFile so save() does not crash
        fp = tmp_path / "t.sage"
        sf = SageFile('PN', 'ver', 'ca', 'pd', 'kw', 'cam', [], 'ls', str(fp))
        view.sage_file = sf

        # Call the internal slot; it should write a file
        view._on_text_field_changed('any_key', 'some_text')
        assert fp.exists()

        # Prepare an image path in the same directory to test image_updated slot
        img = tmp_path / "some.png"
        img.write_text('')
        sf.reference_images = [str(img)]
        view.sage_file = sf
        # Should not raise once reference_images stores an absolute path
        view._on_image_updated('Reference Images', 0, str(img))
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

        monkeypatch.setattr(sage_editor, 'AIModelManager', DummyMM)

        view = self.view
        # Prepare QLineEdits for Project Description and Keywords
        pd = QtWidgets.QLineEdit()
        pd.setText('old')
        kw = QtWidgets.QLineEdit()
        kw.setText('old2')
        view._widgets = {"Project Description": pd, "Keywords": kw}

        # Dummy SageFile with valid directory (camera and empty ref_images)
        d = tempfile.mkdtemp()
        sf = SageFile(
            'n', 'v', 'c', 'd', 'k', 'cam',
            [],  # reference_images
            'ls',
            os.path.join(d, 'f.sage')
        )
        sf.reference_images = []  # no images for context
        view.sage_file = sf

        # Test description-generation action
        view._common_icon_button_clicked_for_sage('TEXT_FIELD_ACTION_Project_Description')
        assert pd.text() == 'ND'

        # Test keywords-generation action
        view._common_icon_button_clicked_for_sage('TEXT_FIELD_ACTION_Keywords')
        assert kw.text() == 'NK'

    def test_get_edited_data_basic(self):
        # Prepare SageFile with initial data
        sf = SageFile(
            'PN', 'ver', 'ca', 'pd', 'kw', 'cam',
            ['a', 'b'],  # reference_images
            'ls',
            '/tmp/x.sage'
        )
        view = self.view
        view.sage_file = sf

        # Prepare widgets for Project Description and Keywords
        pd = QtWidgets.QLineEdit()
        pd.setText('newpd')
        kw = QtWidgets.QLineEdit()
        kw.setText('newkw')

        # Dummy loaders for 4 entries with relative paths
        loaders = []
        for i in range(4):
            loader = self.DummyLoader('/d', self.palette, i)
            loader._relative = ['a', 'b', '', ''][i]
            loaders.append(loader)

        view._widgets = {
            "Project Description": pd,
            "Keywords": kw,
            SageEditorView.REFERENCE_IMAGES_KEY: loaders
        }

        modified = view.get_modified_sage_file().to_dict()
        assert modified['Project Description'] == 'newpd'
        assert modified['Keywords'] == 'newkw'
        # The code will treat empty string as ".", so expect that
        assert modified['Reference Images'] == ['a', 'b', '.', '.']

        # Hidden and locked fields must be preserved
        assert modified['Project Name'] == 'PN'
        assert modified['version'] == 'ver'
        assert modified['createdAt'] == 'ca'
        assert modified['lastSaved'] == 'ls'

    def test_save_functionality(self, tmp_path):
        view = self.view
        fp = tmp_path / "t.sage"
        # Create a SageFile and assign to view
        sf = SageFile('PN', 'ver', 'ca', 'pd', 'kw', 'cam', [], 'ls', str(fp))
        view.sage_file = sf

        # Prepare a Project Description widget to modify data
        pd = QtWidgets.QLineEdit()
        pd.setText('updated')
        view._widgets = {"Project Description": pd}

        # Call save, which should write to the filepath
        view.save()
        loaded = json.loads(fp.read_text(encoding='utf-8'))
        assert loaded['Project Description'] == 'updated'

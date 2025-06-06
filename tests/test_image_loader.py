import os
import pytest

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QResizeEvent

from image_loader import ImageLoaderWidget, ActionIconButton
import config

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

class TestImageLoaderWidget:
    @pytest.fixture(autouse=True)
    def setup_widget(self, tmp_path):
        # Create base_dir and temp image
        self.base_dir = str(tmp_path)
        self.img = tmp_path / 'test.png'
        pix = QtGui.QPixmap(10, 10)
        pix.fill(QtCore.Qt.red)
        pix.save(str(self.img))
        # Palette
        self.palette = config.APP_PALETTE
        # Instantiate widget
        self.w = ImageLoaderWidget(base_dir=self.base_dir, palette=self.palette, index=0)
        return self.w

    def test_apply_styles_border(self):
        w = self.w
        # No pixmap: dashed
        w._pixmap = None
        w._apply_styles()
        ss = w.styleSheet()
        assert 'border: 1px dashed' in ss
        # With pixmap: solid
        w._pixmap = QtGui.QPixmap(5,5)
        w._apply_styles()
        ss2 = w.styleSheet()
        assert 'border: 1px solid' in ss2

    def test_display_pixmap_small_size(self):
        w = self.w
        # Set pixmap
        w._pixmap = QtGui.QPixmap(5,5)
        # resize to zero
        w.resize(2,2)
        # Call display
        w._display_pixmap()
        # Pixmap should be displayed (scaled) even when resize smaller than min constraints
        # Ensure pixmap is set and not null
        assert w.pixmap() is not None
        assert not w.pixmap().isNull()

    def test_display_pixmap_no_image_path(self):
        w = self.w
        w._pixmap = None
        w.image_path = None
        # clear any existing pixmap/text
        w.clear_image(emit_signal=False)
        # Call display
        w._display_pixmap()
        # Should show placeholder text
        assert '+ Add Image' in w.text()
        assert w.pixmap().isNull()

    def test_load_image_valid(self):
        w = self.w
        rel = os.path.basename(str(self.img))
        w.load_image(rel)
        # image_path set
        assert w.image_path == rel
        # pixmap stored
        assert w._pixmap and not w._pixmap.isNull()
        # remove_button should be shown (not hidden)
        # Using isHidden to avoid parent visibility issues in offscreen tests
        assert not w.remove_button.isHidden()
        # style should be solid border
        assert 'border: 1px solid' in w.styleSheet()

    def test_load_image_invalid_file(self, capsys):
        w = self.w
        # create zero-length file
        bad = os.path.join(self.base_dir, 'bad.png')
        open(bad, 'w').close()
        rel = 'bad.png'
        w.load_image(rel)
        out = capsys.readouterr().out
        # Warning printed
        assert 'Could not load image file' in out
        # text indicates invalid image
        assert 'Invalid' in w.text()
        # style dashed border
        assert 'dashed' in w.styleSheet()

    def test_load_image_missing_file(self, capsys):
        w = self.w
        rel = 'missing.png'
        w.load_image(rel)
        out = capsys.readouterr().out
        # Warning printed
        assert 'Image file not found' in out
        assert 'Not Found' in w.text()
        # style dashed
        assert 'dashed' in w.styleSheet()

    def test_clear_image_emits(self, capsys):
        w = self.w
        # Set image_path to non-None
        w.image_path = 'a.png'
        called = []
        w.image_updated.connect(lambda s: called.append(s))
        w.clear_image(emit_signal=True)
        assert called == ['']
        # Placeholder text
        assert '+ Add Image' in w.text()

    def test_on_action_button_clicked_invalid_base(self, monkeypatch, capsys):
        # base_dir invalid
        w = ImageLoaderWidget(base_dir=None, palette=self.palette, index=5)
        # Stub QMessageBox.warning
        called = []
        monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda *args: called.append(True))
        # Connect signal
        got = []
        w.action_clicked.connect(lambda idx: got.append(idx))
        # Call action
        w._on_action_button_clicked('ACT')
        assert called
        assert not got

    def test_on_action_button_clicked_valid(self, tmp_path):
        # valid base_dir
        bd = str(tmp_path)
        w = ImageLoaderWidget(base_dir=bd, palette=self.palette, index=7)
        got = []
        w.action_clicked.connect(lambda idx: got.append(idx))
        # Ensure dir exists
        # Call
        w._on_action_button_clicked('ACT')
        assert got == [7]

    def test_resize_event_calls(self):
        w = self.w
        calls = []
        monkey = lambda: calls.append(True)
        w._update_button_positions = monkey
        w._display_pixmap = monkey
        # create fake event
        old = QtCore.QSize(10,10)
        new = QtCore.QSize(20,20)
        ev = QResizeEvent(new, old)
        w.resizeEvent(ev)
        assert len(calls) == 2

class TestActionIconButton:
    def test_init_and_click(self):
        palette = config.APP_PALETTE
        btn = ActionIconButton(palette, 'ACT', tooltip='T', parent=None)
        assert btn.toolTip() == 'T'
        got = []
        btn.clicked_with_action.connect(lambda s: got.append(s))
        # Simulate click
        btn._on_clicked()
        assert got == ['ACT']

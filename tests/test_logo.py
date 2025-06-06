import importlib
import os
import pytest
from PySide6 import QtWidgets, QtGui, QtCore

logo = importlib.import_module('logo')
config = importlib.import_module('config')
LogoWidget = logo.LogoWidget

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

@pytest.fixture
def default_palette():
    # Use default palette for styling tests
    return {
        'placeholder_bg': '#111111',
        'placeholder_border': '#222222',
        'text_color': '#333333'
    }

def test_import_logo():
    assert logo is not None
    assert hasattr(logo, 'LogoWidget')

def test_setup_ui_and_styles(default_palette, tmp_path):
    # Create a valid image file
    pix = QtGui.QPixmap(4, 4)
    pix.fill(QtCore.Qt.GlobalColor.blue)
    img_path = tmp_path / 'logo.png'
    pix.save(str(img_path), 'PNG')
    # Instantiate widget
    widget = LogoWidget(default_palette, str(img_path))
    # UI setup
    assert hasattr(widget, 'logo_label')
    label = widget.logo_label
    # Alignment
    assert label.alignment() == QtCore.Qt.AlignmentFlag.AlignCenter
    # Minimum size from constants
    assert widget.minimumWidth() == config.MIN_PANEL_WIDTH
    assert widget.minimumHeight() == config.MIN_IMAGE_HEIGHT
    # Style sheet contains placeholder_bg and placeholder_border
    ss = widget.styleSheet()
    assert f"background-color: {default_palette['placeholder_bg']}" in ss
    assert f"border: 1px solid {default_palette['placeholder_border']}" in ss
    # QLabel color
    assert f"color: {default_palette['text_color']}" in ss
    # Logo loaded: original_pixmap set and label pixmap displayed
    assert widget.original_pixmap is not None
    displayed = label.pixmap()
    assert isinstance(displayed, QtGui.QPixmap)
    # No placeholder text
    assert label.text() == ''

def test_load_logo_nonexistent(default_palette, tmp_path, capsys):
    # Non-existent file path
    missing = str(tmp_path / 'no.png')
    widget = LogoWidget(default_palette, missing)
    captured = capsys.readouterr()
    # Should warn about missing file
    assert f"Warning: Logo file not found: {missing}" in captured.out
    # original_pixmap None and label text set
    assert widget.original_pixmap is None
    assert widget.logo_label.text() == 'Logo not found'

def test_load_logo_invalid_image(default_palette, tmp_path, capsys):
    # Create a file that's not a valid image
    bad = tmp_path / 'bad.png'
    bad.write_text('not an image', encoding='utf-8')
    widget = LogoWidget(default_palette, str(bad))
    captured = capsys.readouterr()
    # Should warn about failed load
    assert f"Warning: Failed to load logo image: {str(bad)}" in captured.out
    # original_pixmap None, and label text shows error loading, basename
    assert widget.original_pixmap is None
    expected_text = f"Error loading\n{os.path.basename(str(bad))}"
    assert widget.logo_label.text() == expected_text

def test_resize_event_rescales(tmp_path, default_palette):
    # Prepare a small image
    pix = QtGui.QPixmap(10, 5)
    pix.fill(QtCore.Qt.GlobalColor.green)
    tmp = tmp_path / 'logo3.png'
    pix.save(str(tmp), 'PNG')
    widget = LogoWidget(default_palette, str(tmp))
    # Simulate widget resize to larger size
    old_size = widget.size()
    new_size = QtCore.QSize(200, 100)
    # Override widget.size() to return new_size for scaling calculation
    widget.size = lambda: new_size
    # Fire resize event
    event = QtGui.QResizeEvent(new_size, old_size)
    widget.resizeEvent(event)
    # Available size is new_size minus margins (10px total)
    avail = new_size - QtCore.QSize(10, 10)
    displayed = widget.logo_label.pixmap()
    assert isinstance(displayed, QtGui.QPixmap)
    # Dimensions should now not exceed available size
    assert displayed.size().width() <= avail.width()
    assert displayed.size().height() <= avail.height()

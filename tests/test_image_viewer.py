import importlib
import pytest
from PySide6 import QtWidgets, QtGui, QtCore

image_viewer = importlib.import_module('image_viewer')
config = importlib.import_module('config')
ImageViewerWidget = image_viewer.ImageViewerWidget

@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

@pytest.fixture
def default_palette():
    return config.APP_PALETTE

def test_import_image_viewer():
    assert image_viewer is not None
    assert hasattr(image_viewer, 'ImageViewerWidget')

def test_init_properties(default_palette):
    widget = ImageViewerWidget(default_palette)
    # Initial state: no pixmap, no path
    assert widget._pixmap.isNull()
    assert widget._current_path is None
    # Alignment and minimum size
    assert widget.alignment() == QtCore.Qt.AlignmentFlag.AlignCenter
    assert widget.minimumWidth() >= 100 and widget.minimumHeight() >= 100
    # Style sheet contains background-color and dashed border, and fallback color
    ss = widget.styleSheet()
    assert f"background-color: {default_palette['widget_bg']}" in ss
    assert "dashed" in ss
    # Fallback placeholder_text color (#808080)
    assert "#808080" in ss
    # Placeholder text and tooltip
    assert widget.text() == "No Image Loaded"
    assert widget.toolTip() == ""

def test_load_image_nonexistent(default_palette):
    widget = ImageViewerWidget(default_palette)
    # Empty path
    ret = widget.load_image('')
    assert not ret
    assert widget._pixmap.isNull()
    assert widget._current_path is None
    assert widget.text() == "Image Not Found or Invalid Path"
    assert "dashed" in widget.styleSheet()
    # Nonexistent file
    widget2 = ImageViewerWidget(default_palette)
    ret2 = widget2.load_image('no_such_file.png')
    assert not ret2
    assert widget2._current_path is None
    assert widget2.text().startswith("Image Not Found")

def test_load_image_invalid_content(default_palette, tmp_path, capsys):
    base = tmp_path / 'base'
    base.mkdir()
    bad = base / 'bad.png'
    bad.write_text('not an image', encoding='utf-8')
    widget = ImageViewerWidget(default_palette)
    ret = widget.load_image(str(bad))
    assert not ret
    assert widget._pixmap.isNull()
    assert widget._current_path == str(bad)
    assert "Failed to Load Image" in widget.text()
    # Warning printed
    captured = capsys.readouterr()
    assert f"Warning: Could not load image file: {str(bad)}" in captured.out
    assert "dashed" in widget.styleSheet()

def test_load_image_valid(tmp_path, default_palette):
    base = tmp_path / 'base'
    base.mkdir()
    # Create a valid pixmap file
    pix = QtGui.QPixmap(10, 5)
    pix.fill(QtCore.Qt.GlobalColor.red)
    fp = base / 'img.png'
    pix.save(str(fp), 'PNG')
    widget = ImageViewerWidget(default_palette)
    ret = widget.load_image(str(fp))
    assert ret
    assert not widget._pixmap.isNull()
    assert widget._current_path == str(fp)
    assert widget.text() == ""
    # Solid border applied
    assert "solid" in widget.styleSheet()
    displayed = widget.pixmap()
    assert isinstance(displayed, QtGui.QPixmap)
    # Displayed pixmap fits within widget
    assert displayed.size().width() <= widget.width()
    assert displayed.size().height() <= widget.height()
    assert widget.toolTip() == f"Viewing: {str(fp)}"

def test_clear_method_and_tooltip(default_palette, tmp_path):
    base = tmp_path / 'base'
    base.mkdir()
    pix = QtGui.QPixmap(5,5)
    pix.fill(QtCore.Qt.GlobalColor.blue)
    filep = base / 'i.png'
    pix.save(str(filep),'PNG')
    widget = ImageViewerWidget(default_palette)
    widget.load_image(str(filep))
    # Now clear
    widget.clear()
    assert widget._pixmap.isNull()
    assert widget._current_path is None
    assert widget.pixmap().isNull()
    assert widget.text() == "No Image Loaded"
    assert widget.toolTip() == ""
    assert "dashed" in widget.styleSheet()

def test_resize_event_rescales(tmp_path, default_palette):
    base = tmp_path / 'base'
    base.mkdir()
    pix = QtGui.QPixmap(8,4)
    pix.fill(QtCore.Qt.GlobalColor.yellow)
    imgf = base / 'y.png'
    pix.save(str(imgf),'PNG')
    widget = ImageViewerWidget(default_palette)
    widget.load_image(str(imgf))
    # Simulate resize
    old = widget.size()
    new_size = QtCore.QSize(80,40)
    event = QtGui.QResizeEvent(new_size, old)
    widget.resizeEvent(event)
    displayed = widget.pixmap()
    assert not displayed.isNull()
    # Aspect ratio ~2:1 for 8x4 pixmap
    ratio = displayed.size().width() / displayed.size().height()
    assert pytest.approx(2.0, rel=0.1) == ratio
    
def test_display_scaled_pixmap_clears_when_no_pixmap(default_palette):
    # _display_scaled_pixmap should clear any existing pixmap when _pixmap is null
    widget = ImageViewerWidget(default_palette)
    # Simulate a lingering pixmap on the label
    fake = QtGui.QPixmap(5, 5)
    fake.fill(QtCore.Qt.GlobalColor.red)
    widget.setPixmap(fake)
    # Ensure internal pixmap null
    assert widget._pixmap.isNull()
    # Call display method
    widget._display_scaled_pixmap()
    # The label's pixmap should now be cleared
    assert widget.pixmap().isNull()

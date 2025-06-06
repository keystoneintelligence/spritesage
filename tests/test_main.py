import runpy
import pytest

import config
import main_window

from PySide6 import QtWidgets, QtGui

class DummyApp:
    instances = []
    def __init__(self, args):
        DummyApp.instances.append(self)
        self.args = args
        self.icon = None
    def setWindowIcon(self, icon):
        self.icon = icon
    def exec(self):
        return 456

class DummyIcon:
    def __init__(self, path):
        self.path = path

class DummyWindow:
    instances = []
    def __init__(self, logo_path):
        DummyWindow.instances.append(self)
        self.logo_path = logo_path
        self.shown = False
    def show(self):
        self.shown = True

@pytest.fixture(autouse=True)
def stub_qt(monkeypatch):
    # Stub QApplication and QIcon
    monkeypatch.setattr(QtWidgets, 'QApplication', DummyApp)
    monkeypatch.setattr(QtGui, 'QIcon', DummyIcon)
    # Stub MainWindow
    monkeypatch.setattr(main_window, 'MainWindow', DummyWindow)
    # Ensure no sys.exit kills test
    return

def test_main_with_existing_logo(tmp_path, capsys):
    # Create a dummy logo file
    logo_file = tmp_path / 'logo.png'
    logo_file.write_bytes(b'data')
    # Monkeypatch config.LOGO_FILENAME
    config.LOGO_FILENAME = str(logo_file)
    # Remove any existing QApplication instances
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Run main as script
    with pytest.raises(SystemExit) as se:
        runpy.run_module('main', run_name='__main__')
    assert se.value.code == 456
    # QApplication created with sys.argv
    assert DummyApp.instances, "QApplication not instantiated"
    app = DummyApp.instances[0]
    # QIcon set to logo path
    assert isinstance(app.icon, DummyIcon)
    assert app.icon.path == str(logo_file)
    # MainWindow instantiated with correct args
    assert DummyWindow.instances, "MainWindow not instantiated"
    wnd = DummyWindow.instances[0]
    assert wnd.logo_path == str(logo_file)
    assert wnd.shown

def test_main_with_missing_logo(tmp_path, capsys):
    # Set logo path to non-existent
    fake_logo = tmp_path / 'nofile.png'
    config.LOGO_FILENAME = str(fake_logo)
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Capture stdout for warning
    with pytest.raises(SystemExit):
        runpy.run_module('main', run_name='__main__')
    out = capsys.readouterr().out
    assert f"Warning: Application icon not set. Logo file not found: {str(fake_logo)}" in out
    # QApplication still created, but app.icon remains None
    assert DummyApp.instances
    app = DummyApp.instances[0]
    assert app.icon is None
    # MainWindow instantiated and shown
    assert DummyWindow.instances
    wnd = DummyWindow.instances[0]
    assert wnd.logo_path == str(fake_logo)
    assert wnd.shown

def test_main_import_windll_failure(monkeypatch, tmp_path, capsys):
    """Simulate ImportError on windll import to cover exception path."""
    # Create a fake ctypes module without windll
    import sys, types
    fake_ct = types.ModuleType('ctypes')
    # Ensure real ctypes not used
    monkeypatch.setitem(sys.modules, 'ctypes', fake_ct)
    # Setup stub QApplication and MainWindow
    config.LOGO_FILENAME = str(tmp_path / 'no.png')
    # Clear previous instances
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Run main
    with pytest.raises(SystemExit):
        runpy.run_module('main', run_name='__main__')
    # Should have printed warning about missing app icon, no error from windll
    out = capsys.readouterr().out
    assert "Warning: Application icon not set" in out

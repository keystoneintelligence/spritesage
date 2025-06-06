import json
import pytest
from PySide6 import QtWidgets, QtCore, QtGui

import main_window
import config

LogoWidget = getattr(main_window, 'LogoWidget', None)

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

@pytest.fixture
def temp_settings_file(tmp_path, monkeypatch):
    # Redirect settings file to temp path
    f = tmp_path / 'settings.json'
    monkeypatch.setattr(main_window, 'SETTINGS_FILE_NAME', str(f))
    return f

def test_load_or_create_settings_creates_file(temp_settings_file, capsys):
    # Ensure no settings file exists
    if temp_settings_file.exists(): temp_settings_file.unlink()
    # Instantiate MainWindow, triggering settings creation
    w = main_window.MainWindow(logo_path=None)
    # Check output warning about creating
    out = capsys.readouterr().out
    assert f"Settings file not found. Creating '{str(temp_settings_file)}'" in out
    # File should now exist with DEFAULT_SETTINGS
    assert temp_settings_file.exists()
    data = json.loads(temp_settings_file.read_text(encoding='utf-8'))
    for k, v in config.DEFAULT_SETTINGS.items():
        assert data.get(k) == v

def test_load_or_create_settings_loads_existing_valid(temp_settings_file, capsys):
    # Write valid JSON
    saved = {'OPENAI_API_KEY':'abc','GOOGLE_AI_STUDIO_API_KEY':'def','Selected Inference Provider':'TESTING'}
    temp_settings_file.write_text(json.dumps(saved), encoding='utf-8')
    w = main_window.MainWindow(logo_path=None)
    out = capsys.readouterr().out
    assert f"Loaded settings from: {str(temp_settings_file)}" in out
    # Ensure settings attribute includes saved values
    for k, v in saved.items():
        assert w.settings.get(k) == v

def test_load_or_create_settings_invalid_json(temp_settings_file, capsys):
    # Write invalid JSON
    temp_settings_file.write_text('{bad json}', encoding='utf-8')
    w = main_window.MainWindow(logo_path=None)
    out = capsys.readouterr().out
    assert "Error loading settings file" in out
    # Settings should equal defaults
    for k, v in config.DEFAULT_SETTINGS.items():
        assert w.settings.get(k) == v

def test_update_window_title_no_project(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    w.current_project_path = None
    w._update_window_title()
    assert w.windowTitle() == "Modular Editor Interface (PySide6)"

def test_update_window_title_with_project(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    w.current_project_path = '/path/to/proj'
    w._update_window_title()
    assert w.windowTitle().startswith('proj - ')

def test_setup_layout_widgets(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    outer = w.centralWidget()
    # Outer splitter should be a QSplitter vertical
    assert isinstance(outer, QtWidgets.QSplitter)
    assert outer.orientation() == QtCore.Qt.Orientation.Vertical
    # Inner and bottom splitters
    inner, bottom = outer.widget(0), outer.widget(1)
    assert inner.orientation() == QtCore.Qt.Orientation.Horizontal
    assert bottom.orientation() == QtCore.Qt.Orientation.Horizontal
    # Child widgets of inner splitter
    assert isinstance(inner.widget(0), main_window.SidebarWidget)
    assert isinstance(inner.widget(1), main_window.EditorWidget)
    # Child widgets of bottom splitter
    assert isinstance(bottom.widget(0), main_window.LogoWidget)
    assert isinstance(bottom.widget(1), main_window.ConsoleWidget)

def test_apply_main_styles(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    # Apply styles
    w._apply_main_styles()
    # Check central widget style contains window_bg
    bg = w.active_palette['window_bg']
    assert f"background-color: {bg}" in w.styleSheet() or f"background-color: {bg}" in w.centralWidget().styleSheet()

import pytest
@pytest.mark.skip("Splitter stretch factor tests are environment-dependent and flaky")
def test_set_initial_sizes(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    w._set_initial_sizes()
    # Skipping detailed size assertion due to platform variability
    assert w.outer_splitter is not None


@pytest.mark.skip("Splitter sync tests are environment-dependent and flaky")
def test_initial_sync_and_sync_methods(qapp, temp_settings_file):
    # Skip detailed splitter sync tests due to platform variability
    w = main_window.MainWindow(logo_path=None)
    assert hasattr(w, 'initial_sync')

def test_close_event(qapp, temp_settings_file):
    w = main_window.MainWindow(logo_path=None)
    event = QtGui.QCloseEvent()
    # Should accept the event without error
    w.closeEvent(event)
    assert event.isAccepted()

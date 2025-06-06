import importlib
import os
import re
import pytest

config = importlib.import_module('config')

def test_import_config():
    assert config is not None

def test_base_dir_and_paths():
    expected_base_dir = os.path.abspath(".")
    assert config.base_dir() == expected_base_dir
    expected_logo_path = os.path.normpath(os.path.join(config.base_dir(), config.LOGO_FILENAME))
    assert os.path.normpath(config.LOGO_FILENAME) == expected_logo_path
    expected_settings_file = './.sagesettings'
    assert config.SETTINGS_FILE_NAME == expected_settings_file

def test_basic_constants():
    assert config.MIN_PANEL_WIDTH > 0
    assert config.MIN_IMAGE_HEIGHT > 0
    assert config.MIN_EDITOR_CONSOLE_WIDTH > 0
    assert config.MIN_EDITOR_CONSOLE_HEIGHT > 0
    assert isinstance(config.SAGE_FILE_EXTENSION, str) and config.SAGE_FILE_EXTENSION.startswith('.')
    assert isinstance(config.IMAGE_GRID_ITEM_SIZE, int) and config.IMAGE_GRID_ITEM_SIZE > 0

def test_default_settings_structure():
    assert isinstance(config.DEFAULT_SETTINGS, dict)
    expected_keys = {'OPENAI_API_KEY', 'GOOGLE_AI_STUDIO_API_KEY', 'Selected Inference Provider'}
    assert set(config.DEFAULT_SETTINGS.keys()) == expected_keys
    assert config.DEFAULT_SETTINGS['Selected Inference Provider'] == 'TESTING'

def test_app_palette_keys_and_values():
    assert isinstance(config.APP_PALETTE, dict)
    hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
    palette = config.APP_PALETTE
    for key, value in palette.items():
        assert isinstance(value, str)
        assert hex_pattern.match(value), f"Value for {key} is not a valid hex color"

def test_sidebar_depth_colors_qcolor():
    qtgui = pytest.importorskip('PySide6.QtGui')
    expected_codes = ['#3498db', '#2ecc71', '#f1c40f', '#e67e22', '#e74c3c', '#9b59b6', '#1abc9c', '#7f8c8d']
    assert isinstance(config.SIDEBAR_DEPTH_COLORS, list)
    assert len(config.SIDEBAR_DEPTH_COLORS) == len(expected_codes)
    for qc, expected in zip(config.SIDEBAR_DEPTH_COLORS, expected_codes):
        assert isinstance(qc, qtgui.QColor)
        assert qc.name().lower() == expected

def test_icon_paths_are_strings():
    icon_attrs = [attr for attr in dir(config) if attr.endswith('_ICON_PATH')]
    for attr in icon_attrs:
        value = getattr(config, attr)
        assert isinstance(value, str)
        ext = os.path.splitext(value)[1].lower()
        assert ext in {'.png', '.ico', '.svg', '.bmp'}

import importlib
import pytest
import json

editor = importlib.import_module('editor')
config = importlib.import_module('config')

qtwidgets = pytest.importorskip('PySide6.QtWidgets')
qtc = pytest.importorskip('PySide6.QtCore')
QApplication = qtwidgets.QApplication
EditorWidget = editor.EditorWidget

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app

@pytest.fixture
def default_palette():
    return config.APP_PALETTE

def test_load_file_none_shows_placeholder(default_palette):
    widget = EditorWidget(default_palette)
    widget.load_file(None)
    pt = widget.plain_text_editor
    assert pt.toPlainText() == ''
    assert 'Select a valid file' in pt.placeholderText()
    assert pt.isReadOnly()
    assert widget.stacked_layout.currentWidget() == pt
    assert widget.current_file_path is None

def test_read_file_content_success(default_palette, tmp_path):
    # _read_file_content should return the exact content of the file
    widget = EditorWidget(default_palette)
    test_file = tmp_path / 'readme.txt'
    content = 'Line1\nLine2\n'
    test_file.write_text(content, encoding='utf-8')
    result = widget._read_file_content(str(test_file))
    assert result == content

def test_load_text_file_fallback(default_palette, tmp_path):
    # load_file should handle text files and display content in plain_text_editor
    widget = EditorWidget(default_palette)
    txt_file = tmp_path / 'sample.txt'
    text = 'Hello, world!'
    txt_file.write_text(text, encoding='utf-8')
    widget.load_file(str(txt_file))
    pt = widget.plain_text_editor
    assert pt.toPlainText() == text
    assert not pt.isReadOnly()
    assert widget.stacked_layout.currentWidget() == pt
    assert widget.current_file_path == str(txt_file)

def test_load_file_nonexistent(default_palette, tmp_path):
    widget = EditorWidget(default_palette)
    nonexist = tmp_path / 'nofile.txt'
    widget.load_file(str(nonexist))
    pt = widget.plain_text_editor
    assert 'Selected item is not a file' in pt.placeholderText()
    assert widget.current_file_path is None

def test_load_sage_file_success(default_palette, tmp_path, monkeypatch):
    file = tmp_path / 'a.sage'
    file.write_text('{"foo": "bar"}', encoding='utf-8')
    monkeypatch.setattr(editor, 'SageFile', type('S', (), {})())
    editor.SageFile.from_json = staticmethod(lambda p: {'dummy': True})
    class P(qtwidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.console_widget = self
            self.logs = []
        def log_message(self, m):
            self.logs.append(m)
    parent = P()
    widget = EditorWidget(default_palette, parent=parent)
    # stub load_data to avoid real SageEditorView logic
    loaded = []
    widget.sage_editor.load_data = lambda sf: loaded.append(sf)
    widget.load_file(str(file))
    # verify sage load was called with stubbed data
    assert loaded == [{'dummy': True}]
    # verify view switched to sage editor
    assert widget.stacked_layout.currentWidget() == widget.sage_editor
    # verify console log
    assert any('Opened .sage file' in m for m in parent.logs)
    # verify current_file_path remains set
    assert widget.current_file_path == str(file)

def test_load_sprite_file_success(default_palette, tmp_path, monkeypatch):
    file = tmp_path / 'b.sprite'
    file.write_text('', encoding='utf-8')
    monkeypatch.setattr(editor, 'SageFile', type('S', (), {})())
    editor.SageFile.from_json = staticmethod(lambda p: {})
    class P(qtwidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.console_widget = self
            self.logs = []
        def log_message(self, m):
            self.logs.append(m)
    parent = P()
    widget = EditorWidget(default_palette, parent=parent)
    widget.sage_editor.sage_file = {'x': 1}
    calls = []
    widget.sprite_editor.load_sprite_data = lambda path, sf: calls.append((path, sf))
    widget.load_file(str(file))
    # verify current_file_path was set
    assert widget.current_file_path == str(file)
    # verify view switched to sprite editor
    assert widget.stacked_layout.currentWidget() == widget.sprite_editor
    # verify sprite_editor.load_sprite_data was called with correct arguments
    assert calls and calls[0][0] == str(file)
    # verify console log
    assert any('Opened .sprite file' in m for m in parent.logs)

    # Test error path for sprite loading
    error_file = tmp_path / 'fail.sprite'
    error_file.write_text('', encoding='utf-8')
    widget_err = EditorWidget(default_palette)
    def bad_loader(path, sage_file):
        raise RuntimeError('sprite load failed')
    widget_err.sprite_editor.load_sprite_data = bad_loader
    widget_err.load_file(str(error_file))
    err_pt = widget_err.plain_text_editor
    # Error message should be shown
    assert 'Error loading .sprite file' in err_pt.toPlainText()
    # State should be reset
    assert widget_err.current_file_path is None
    assert err_pt.isReadOnly()
    assert widget_err.stacked_layout.currentWidget() == err_pt

def test_load_image_file_success(default_palette, tmp_path, monkeypatch):
    file = tmp_path / 'c.png'
    file.write_bytes(b'')
    class P(qtwidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.console_widget = self
            self.logs = []
        def log_message(self, m):
            self.logs.append(m)
    parent = P()
    widget = EditorWidget(default_palette, parent=parent)
    widget.image_viewer.load_image = lambda p: True
    widget.load_file(str(file))
    # verify current_file_path was set
    assert widget.current_file_path == str(file)
    # verify view switched to image viewer
    assert widget.stacked_layout.currentWidget() == widget.image_viewer
    assert any('Opened image file' in m for m in parent.logs)

def test_load_image_file_failure(default_palette, tmp_path, monkeypatch):
    file = tmp_path / 'd.png'
    file.write_bytes(b'')
    class P(qtwidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.console_widget = self
            self.logs = []
        def log_message(self, m):
            self.logs.append(m)
    parent = P()
    widget = EditorWidget(default_palette, parent=parent)
    widget.image_viewer.load_image = lambda p: False
    widget.load_file(str(file))
    pt = widget.plain_text_editor
    assert widget.current_file_path is None
    assert widget.stacked_layout.currentWidget() == pt
    assert any('Error loading image' in m for m in parent.logs)

def test_log_message_dispatch(default_palette):
    class P(qtwidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.console_widget = self
            self.logs = []
        def log_message(self, m):
            self.logs.append(m)
    parent = P()
    widget = EditorWidget(default_palette, parent=parent)
    widget._log_message('xyz')
    assert parent.logs == ['xyz']

def test_load_text_file_read_error(default_palette, qapp):
    # Simulate a read error in loading text file and ensure error is displayed
    widget = EditorWidget(default_palette)
    # Monkeypatch read to raise exception
    widget._read_file_content = lambda p: (_ for _ in ()).throw(Exception('fail read'))
    # Set a dummy current file path
    widget.current_file_path = 'dummy.txt'
    # Call the private load method directly
    widget._load_text_file('dummy.txt')
    pt = widget.plain_text_editor
    text = pt.toPlainText()
    assert 'Error reading or loading text file' in text
    # Should be read-only and show in plain text editor
    assert pt.isReadOnly()
    # Current file path should be reset on error
    assert widget.current_file_path is None
    # Stacked layout should show the plain text editor
    assert widget.stacked_layout.currentWidget() == pt

def test_show_error_in_plaintext_raw_content(default_palette, qapp):
    # Ensure raw_content is appended when provided
    widget = EditorWidget(default_palette)
    widget._show_error_in_plaintext('error occurred', raw_content='raw data')
    pt = widget.plain_text_editor
    text = pt.toPlainText()
    assert 'error occurred' in text
    assert '--- Raw File Content ---' in text
    assert 'raw data' in text
    # Should be read-only and visible in editor
    assert pt.isReadOnly()
    assert widget.stacked_layout.currentWidget() == pt

def test_log_message_fallback_print(default_palette, qapp, capsys):
    # Ensure _log_message falls back to printing when no console_widget is found
    parent_dummy = qtwidgets.QWidget()
    # Ensure no console_widget attribute
    if hasattr(parent_dummy, 'console_widget'):
        delattr(parent_dummy, 'console_widget')
    widget = EditorWidget(default_palette, parent=parent_dummy)
    message = 'fallback log'
    widget._log_message(message)
    captured = capsys.readouterr()
    assert f'LOG (Editor): {message}' in captured.out

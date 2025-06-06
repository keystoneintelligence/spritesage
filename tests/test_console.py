import importlib
import pytest

console = importlib.import_module('console')
config = importlib.import_module('config')

qtwidgets = pytest.importorskip('PySide6.QtWidgets')
QApplication = qtwidgets.QApplication
ConsoleWidget = console.ConsoleWidget

def test_import_console():
    module = importlib.import_module('console')
    assert module is not None
    
@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_init_properties(qapp, monkeypatch):
    monkeypatch.setattr(console.time, 'strftime', lambda fmt: "12:34:56")
    palette = {'console_bg': '#AAAAAA', 'text_color': '#BBBBBB', 'placeholder_border': '#CCCCCC'}
    widget = ConsoleWidget(palette)
    assert widget.isReadOnly()
    assert widget.placeholderText() == "Console / Log Area"
    assert widget.minimumWidth() == config.MIN_EDITOR_CONSOLE_WIDTH
    assert widget.minimumHeight() == config.MIN_EDITOR_CONSOLE_HEIGHT
    ss = widget.styleSheet()
    assert f"background-color: {palette['console_bg']}" in ss
    assert f"color: {palette['text_color']}" in ss
    assert f"border: 1px solid {palette['placeholder_border']}" in ss
    assert "font-family: Consolas" in ss
    text = widget.toPlainText().strip()
    assert text == "[12:34:56] Console Initialized. Create or load a project."

def test_log_message_appends_and_scrolls(qapp, monkeypatch):
    monkeypatch.setattr(console.time, 'strftime', lambda fmt: "01:02:03")
    palette = {'console_bg': '#FFFFFF', 'text_color': '#000000', 'placeholder_border': '#CCCCCC'}
    widget = ConsoleWidget(palette)
    initial_lines = widget.toPlainText().splitlines()
    widget.log_message("Test message")
    lines = widget.toPlainText().splitlines()
    assert len(lines) == len(initial_lines) + 1
    assert lines[-1] == "[01:02:03] Test message"
    vsb = widget.verticalScrollBar()
    assert vsb.value() == vsb.maximum()

import runpy
import sys
import pytest

from spritesage import config
from spritesage import main as app_main
from spritesage import main_window

from PySide6 import QtWidgets, QtGui


class DummyApp:
    instances = []

    def __init__(self, args):
        DummyApp.instances.append(self)
        self.args = args
        self.icon = None
        self.stylesheet = ""

    def setWindowIcon(self, icon):
        self.icon = icon

    def setStyleSheet(self, stylesheet):
        self.stylesheet = stylesheet

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
    monkeypatch.setattr(QtWidgets, "QApplication", DummyApp)
    monkeypatch.setattr(QtGui, "QIcon", DummyIcon)
    # Stub MainWindow
    monkeypatch.setattr(main_window, "MainWindow", DummyWindow)
    # Ensure no sys.exit kills test
    return


def test_main_with_existing_logo(tmp_path, capsys):
    # Create a dummy logo file
    logo_file = tmp_path / "logo.png"
    logo_file.write_bytes(b"data")
    # Monkeypatch config.LOGO_FILENAME
    config.LOGO_FILENAME = str(logo_file)
    # Remove any existing QApplication instances
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Run main as script
    with pytest.raises(SystemExit) as se:
        runpy.run_module("spritesage.main", run_name="__main__")
    assert se.value.code == 456
    # QApplication created with sys.argv
    assert DummyApp.instances, "QApplication not instantiated"
    app = DummyApp.instances[0]
    assert "QMessageBox QLabel#qt_msgbox_label" in app.stylesheet
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
    fake_logo = tmp_path / "nofile.png"
    config.LOGO_FILENAME = str(fake_logo)
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Capture stdout for warning
    with pytest.raises(SystemExit):
        runpy.run_module("spritesage.main", run_name="__main__")
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

    fake_ct = types.ModuleType("ctypes")
    # Ensure real ctypes not used
    monkeypatch.setitem(sys.modules, "ctypes", fake_ct)
    # Setup stub QApplication and MainWindow
    config.LOGO_FILENAME = str(tmp_path / "no.png")
    # Clear previous instances
    DummyApp.instances.clear()
    DummyWindow.instances.clear()
    # Run main
    with pytest.raises(SystemExit):
        runpy.run_module("spritesage.main", run_name="__main__")
    # Should have printed warning about missing app icon, no error from windll
    out = capsys.readouterr().out
    assert "Warning: Application icon not set" in out


def test_null_startup_screen_methods_are_noops():
    screen = app_main.NullStartupScreen()

    screen.show()
    screen.set_status("Anything", progress=50, busy=True)
    screen.finish(object())
    screen.close()


def test_create_startup_screen_returns_null_for_non_qt_app():
    screen = app_main._create_startup_screen(app=object(), logo_path="logo.png")

    assert isinstance(screen, app_main.NullStartupScreen)


def test_create_startup_screen_shows_and_sets_initial_status(monkeypatch):
    created = []

    class FakeApp:
        def processEvents(self):
            pass

    class FakeStartupScreen:
        def __init__(self, logo_path=None, palette=None):
            self.logo_path = logo_path
            self.palette = palette
            self.shown = False
            self.statuses = []
            created.append(self)

        def show(self):
            self.shown = True

        def set_status(self, *args):
            self.statuses.append(args)

    monkeypatch.setattr(app_main, "StartupScreen", FakeStartupScreen)

    screen = app_main._create_startup_screen(FakeApp(), "logo.png")

    assert screen is created[0]
    assert screen.logo_path == "logo.png"
    assert screen.palette == app_main.APP_PALETTE
    assert screen.shown is True
    assert screen.statuses == [("Preparing application...", 5)]


def test_write_crash_log_falls_back_to_cwd(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(app_main, "_startup_log_dir", lambda: blocked)
    monkeypatch.setattr(app_main.Path, "cwd", staticmethod(lambda: fallback_dir))

    path = app_main._write_crash_log("details")

    assert path is not None
    assert path.parent == fallback_dir
    assert path.name.startswith("startup-error-")
    assert path.read_text(encoding="utf-8") == "details"


def test_show_error_dialog_writes_details_to_message_box(monkeypatch, tmp_path):
    created = []
    log_path = tmp_path / "startup-error.log"
    monkeypatch.setattr(app_main, "_write_crash_log", lambda details: log_path)

    class FakeMessageBox:
        class Icon:
            Critical = "critical"

        def __init__(self):
            self.icon = None
            self.title = ""
            self.text = ""
            self.details = ""
            self.executed = False
            created.append(self)

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setDetailedText(self, details):
            self.details = details

        def exec(self):
            self.executed = True

    monkeypatch.setattr(app_main.QtWidgets, "QMessageBox", FakeMessageBox)

    app_main._show_error_dialog("Title", "Message", "Traceback")

    box = created[0]
    assert box.icon == "critical"
    assert box.title == "Title"
    assert "Message" in box.text
    assert str(log_path) in box.text
    assert box.details == "Traceback"
    assert box.executed is True


def test_install_exception_hook_reports_uncaught_exception(monkeypatch, capsys):
    shown = []
    original_hook = sys.excepthook
    monkeypatch.setattr(sys, "excepthook", original_hook)
    monkeypatch.setattr(
        app_main,
        "_show_error_dialog",
        lambda title, message, details: shown.append((title, message, details)),
    )

    app_main._install_exception_hook()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_traceback)

    err = capsys.readouterr().err
    assert "RuntimeError: boom" in err
    assert shown[0][0] == "Sprite Sage Error"
    assert "unexpected error" in shown[0][1]
    assert "RuntimeError: boom" in shown[0][2]


def test_create_main_window_passes_startup_progress_when_supported(monkeypatch):
    monkeypatch.setattr(app_main, "LOGO_FILENAME", "logo.png")
    statuses = []

    class FakeStartup:
        def set_status(self, *args):
            statuses.append(args)

    class WindowWithProgress:
        def __init__(self, logo_path, startup_progress):
            self.logo_path = logo_path
            self.startup_progress = startup_progress

    window = app_main._create_main_window(WindowWithProgress, FakeStartup())

    assert window.logo_path == "logo.png"
    window.startup_progress("Loading", 25)
    assert statuses == [("Loading", 25)]


def test_create_main_window_omits_startup_progress_when_not_supported(monkeypatch):
    monkeypatch.setattr(app_main, "LOGO_FILENAME", "logo.png")

    class WindowWithoutProgress:
        def __init__(self, logo_path):
            self.logo_path = logo_path

    window = app_main._create_main_window(WindowWithoutProgress, app_main.NullStartupScreen())

    assert window.logo_path == "logo.png"

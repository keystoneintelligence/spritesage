from PySide6 import QtCore, QtGui, QtWidgets
import pytest

from spritesage.startup_screen import StartupScreen


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_startup_screen_constructs_without_logo_and_applies_styles():
    palette = {
        "window_bg": "#101010",
        "widget_bg": "#202020",
        "text_color": "#303030",
        "label_color": "#404040",
        "tree_item_selected_bg": "#505050",
        "placeholder_border": "#606060",
    }

    screen = StartupScreen(logo_path=None, palette=palette)

    assert screen.objectName() == "StartupScreen"
    assert screen.logo_label.pixmap().isNull()
    assert screen.status_label.text() == "Preparing application..."
    assert screen.progress_bar.value() == 0
    assert "#101010" in screen.styleSheet()
    assert "#505050" in screen.styleSheet()


def test_startup_screen_loads_logo_when_pixmap_is_valid(tmp_path):
    logo_path = tmp_path / "logo.png"
    pixmap = QtGui.QPixmap(10, 10)
    pixmap.fill(QtCore.Qt.GlobalColor.red)
    assert pixmap.save(str(logo_path))

    screen = StartupScreen(logo_path=str(logo_path))

    assert not screen.logo_label.pixmap().isNull()


def test_startup_screen_status_supports_busy_and_clamped_progress():
    screen = StartupScreen()

    screen.set_status("Working", progress=150)
    assert screen.status_label.text() == "Working"
    assert screen.progress_bar.value() == 100

    screen.set_status("Busy", busy=True)
    assert screen.progress_bar.minimum() == 0
    assert screen.progress_bar.maximum() == 0

    screen.set_status("Back", progress=-10, busy=False)
    assert screen.progress_bar.maximum() == 100
    assert screen.progress_bar.value() == 0


def test_startup_screen_finish_closes_and_activates_window():
    screen = StartupScreen()

    class FakeWindow:
        def __init__(self):
            self.activated = False

        def activateWindow(self):
            self.activated = True

    window = FakeWindow()
    screen.finish(window)

    assert screen.status_label.text() == "Ready."
    assert screen.progress_bar.value() == 100
    assert window.activated is True

"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import sys
import os
import inspect
import traceback
from datetime import datetime
from pathlib import Path

from PySide6 import QtWidgets, QtGui

# Import configuration variables
from config import APP_PALETTE, LOGO_FILENAME
from startup_screen import StartupScreen

# Optional: Set AppUserModelID for Windows taskbar icon grouping
try:
    from ctypes import windll
    myappid = u'mycompany.myproduct.sageeditor.1' # Adapt as needed
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass # Fails on non-Windows platforms


class NullStartupScreen:
    def show(self):
        pass

    def set_status(self, message, progress=None, busy=False):
        pass

    def finish(self, main_window):
        pass

    def close(self):
        pass


def _create_startup_screen(app, logo_path):
    if not callable(getattr(app, "processEvents", None)):
        return NullStartupScreen()
    screen = StartupScreen(logo_path=logo_path, palette=APP_PALETTE)
    screen.show()
    screen.set_status("Preparing application...", 5)
    return screen


def _startup_log_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "SpriteSage" / "logs"


def _write_crash_log(details):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"startup-error-{timestamp}.log"
    candidate_dirs = [_startup_log_dir(), Path.cwd()]
    for directory in candidate_dirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / filename
            path.write_text(details, encoding="utf-8")
            return path
        except OSError:
            continue
    return None


def _show_error_dialog(title, message, details):
    log_path = _write_crash_log(details)
    if log_path:
        message = f"{message}\n\nA diagnostic log was written to:\n{log_path}"

    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    box.setDetailedText(details)
    box.exec()


def _install_exception_hook():
    def handle_exception(exc_type, exc_value, exc_traceback):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(details, file=sys.stderr)
        _show_error_dialog(
            "Sprite Sage Error",
            "Sprite Sage encountered an unexpected error.",
            details,
        )

    sys.excepthook = handle_exception


def _create_main_window(main_window_class, startup_screen):
    kwargs = {"logo_path": LOGO_FILENAME}
    try:
        signature = inspect.signature(main_window_class)
    except (TypeError, ValueError):
        signature = None

    if signature and "startup_progress" in signature.parameters:
        kwargs["startup_progress"] = startup_screen.set_status
    return main_window_class(**kwargs)


def main():
    app = QtWidgets.QApplication(sys.argv)
    if callable(getattr(app, "setApplicationName", None)):
        app.setApplicationName("Sprite Sage")
    _install_exception_hook()
    startup_screen = NullStartupScreen()

    try:
        startup_screen = _create_startup_screen(app, LOGO_FILENAME)

        # Set application icon
        startup_screen.set_status("Loading application icon...", 12)
        if os.path.exists(LOGO_FILENAME):
            app.setWindowIcon(QtGui.QIcon(LOGO_FILENAME))
        else:
            print(f"Warning: Application icon not set. Logo file not found: {LOGO_FILENAME}")

        # Import after the splash screen is visible so slow module imports have UI feedback.
        startup_screen.set_status("Loading application modules...", 25, busy=True)
        from main_window import MainWindow

        startup_screen.set_status("Creating main window...", 35)
        window = _create_main_window(MainWindow, startup_screen)

        startup_screen.set_status("Opening workspace...", 95)
        window.show()
        startup_screen.finish(window)

        # Start the application event loop
        return app.exec()
    except Exception:
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        startup_screen.close()
        _show_error_dialog(
            "Sprite Sage Startup Error",
            "Sprite Sage could not finish starting.",
            details,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

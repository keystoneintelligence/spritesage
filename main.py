"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import sys
import os
from PySide6 import QtWidgets, QtGui

# Import configuration variables
from config import LOGO_FILENAME

# Import the main window class
from main_window import MainWindow

# Optional: Set AppUserModelID for Windows taskbar icon grouping
try:
    from ctypes import windll
    myappid = u'mycompany.myproduct.sageeditor.1' # Adapt as needed
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass # Fails on non-Windows platforms

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Set application icon
    if os.path.exists(LOGO_FILENAME):
        app.setWindowIcon(QtGui.QIcon(LOGO_FILENAME))
    else:
        print(f"Warning: Application icon not set. Logo file not found: {LOGO_FILENAME}")

    # Create and show the main window
    window = MainWindow(logo_path=LOGO_FILENAME)
    window.show()

    # Start the application event loop
    sys.exit(app.exec())
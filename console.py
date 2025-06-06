"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import time
from PySide6 import QtWidgets

# Import constants from config.py (adjust path if necessary)
from config import MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT

class ConsoleWidget(QtWidgets.QPlainTextEdit):
    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.setReadOnly(True)
        self.setPlaceholderText("Console / Log Area")
        self.setMinimumSize(MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT)
        self._apply_styles()
        self.log_message("Console Initialized. Create or load a project.")

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {self.palette['console_bg']};
                color: {self.palette['text_color']};
                border: 1px solid {self.palette['placeholder_border']};
                font-family: Consolas, Courier New, monospace; /* Added monospace font */
            }}
        """)

    def log_message(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.appendPlainText(f"[{timestamp}] {message}")
        # Ensure the latest message is visible
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
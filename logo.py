"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
from PySide6 import QtWidgets, QtCore, QtGui

from config import MIN_PANEL_WIDTH, MIN_IMAGE_HEIGHT

class LogoWidget(QtWidgets.QWidget):
    def __init__(self, palette, logo_path, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.logo_path = logo_path
        self.original_pixmap = None
        self.setMinimumSize(MIN_PANEL_WIDTH, MIN_IMAGE_HEIGHT)
        self._setup_ui()
        self._load_logo()
        self._apply_styles()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        self.logo_label = QtWidgets.QLabel(self)
        self.logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.logo_label)

    def _load_logo(self):
        if self.logo_path and os.path.exists(self.logo_path):
            self.original_pixmap = QtGui.QPixmap(self.logo_path)
            if self.original_pixmap.isNull():
                print(f"Warning: Failed to load logo image: {self.logo_path}")
                self.logo_label.setText(f"Error loading\n{os.path.basename(self.logo_path)}")
                self.original_pixmap = None
            else:
                 self.logo_label.setPixmap(self.original_pixmap.scaled(
                    self.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation))
        else:
            print(f"Warning: Logo file not found: {self.logo_path}")
            self.logo_label.setText("Logo not found")

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        if self.original_pixmap:
            # Subtract margins from available size for scaling
            available_size = self.size() - QtCore.QSize(10, 10) # 5px margin on each side
            scaled_pixmap = self.original_pixmap.scaled(
                available_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)
            self.logo_label.setPixmap(scaled_pixmap)


    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {self.palette['placeholder_bg']};
                border: 1px solid {self.palette['placeholder_border']};
            }}
            QLabel {{
                color: {self.palette['text_color']};
                border: none; background-color: transparent;
            }}
        """)

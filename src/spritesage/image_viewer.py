"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtCore import Qt


class ImageViewerWidget(QtWidgets.QLabel):
    """
    A simple widget to display an image, scaling it to fit while preserving aspect ratio.
    """
    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._pixmap = QtGui.QPixmap() # Store the original pixmap
        self._current_path = None

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(100, 100) # Set a reasonable minimum size
        self._apply_styles()
        self.setText("No Image Loaded") # Placeholder text

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {self.palette.get('widget_bg', '#2B2B2B')};
                color: {self.palette.get('placeholder_text', '#808080')};
                border: 1px dashed {self.palette.get('placeholder_border', '#555555')};
            }}
        """)
        # If an image is loaded, change border maybe?
        if not self._pixmap.isNull():
            self.setStyleSheet(self.styleSheet().replace("dashed", "solid"))
        else:
             self.setStyleSheet(self.styleSheet().replace("solid", "dashed"))

    def load_image(self, file_path: str) -> bool:
        """
        Loads an image from the given file path.
        Returns True on success, False otherwise.
        """
        if not file_path or not os.path.isfile(file_path):
            self._pixmap = QtGui.QPixmap() # Clear pixmap
            self._current_path = None
            self.setText("Image Not Found or Invalid Path")
            self._apply_styles() # Update border to dashed
            return False

        loaded_pixmap = QtGui.QPixmap(file_path)
        if loaded_pixmap.isNull():
            self._pixmap = QtGui.QPixmap() # Clear pixmap
            self._current_path = file_path # Keep path for potential debugging
            self.setText(f"Failed to Load Image:\n{os.path.basename(file_path)}")
            self._apply_styles() # Update border to dashed
            print(f"Warning: Could not load image file: {file_path}")
            return False
        else:
            self._pixmap = loaded_pixmap
            self._current_path = file_path
            self.setText("") # Clear placeholder text
            self._apply_styles() # Update border to solid
            self._display_scaled_pixmap()
            self.setToolTip(f"Viewing: {file_path}")
            return True

    def clear(self):
        """Clears the displayed image."""
        self._pixmap = QtGui.QPixmap()
        self._current_path = None
        self.setPixmap(QtGui.QPixmap()) # Clear the displayed pixmap
        self.setText("No Image Loaded")
        self.setToolTip("")
        self._apply_styles() # Reset styles (dashed border)

    def _display_scaled_pixmap(self):
        """Scales the stored pixmap to fit the widget size and displays it."""
        if self._pixmap.isNull():
            self.setPixmap(QtGui.QPixmap()) # Ensure it's cleared if pixmap is null
            return

        # Scale pixmap to fit the label's current size, keeping aspect ratio
        scaled_pixmap = self._pixmap.scaled(self.size(),
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled_pixmap)

    def resizeEvent(self, event: QtGui.QResizeEvent):
        """Handle widget resize events to rescale the displayed image."""
        super().resizeEvent(event)
        # Only rescale if we have a valid pixmap loaded
        if not self._pixmap.isNull():
            self._display_scaled_pixmap()

    # Override mouse events if needed to prevent interactions,
    # but QLabel is generally non-interactive anyway.
    # def mousePressEvent(self, ev: QtGui.QMouseEvent) -> None:
    #     pass # Ignore clicks
    # def mouseDoubleClickEvent(self, ev: QtGui.QMouseEvent) -> None:
    #     pass # Ignore double clicks
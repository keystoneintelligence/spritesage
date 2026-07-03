"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from __future__ import annotations

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from .config import build_application_stylesheet
from .image_polish import PolishOptions, clean_background_with_ben2, polish_image
from .utils import call_with_busy


class ImagePolishDialog(QtWidgets.QDialog):
    def __init__(
        self,
        image: Image.Image,
        *,
        palette: dict,
        title: str = "Polish Image",
        parent=None,
    ):
        super().__init__(parent)
        self.app_palette = palette
        self.source_image = image.convert("RGBA")
        self.working_image = self.source_image.copy()
        self.polished_image = self.source_image.copy()

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(720, 430)
        self.setStyleSheet(build_application_stylesheet(self.app_palette))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        preview_row = QtWidgets.QHBoxLayout()
        preview_row.setSpacing(10)
        self.before_preview = _PreviewLabel("Before", self.app_palette)
        self.after_preview = _PreviewLabel("After", self.app_palette)
        preview_row.addWidget(self.before_preview, 1)
        preview_row.addWidget(self.after_preview, 1)
        root.addLayout(preview_row, 1)

        controls_row = QtWidgets.QHBoxLayout()
        controls_row.setSpacing(12)
        self.clean_background_button = QtWidgets.QPushButton("Clean Transparent Background")
        self.clean_background_button.setToolTip("Run BEN2 background removal on this image")
        self.trim_padding_check = QtWidgets.QCheckBox("Trim empty padding")
        self.trim_padding_check.setChecked(True)
        self.center_canvas_check = QtWidgets.QCheckBox("Center on original canvas")
        self.center_canvas_check.setChecked(True)
        self.outline_check = QtWidgets.QCheckBox("Add 1px outline")
        self.outline_check.setChecked(False)

        self.clean_background_button.clicked.connect(self._clean_background)
        controls_row.addWidget(self.clean_background_button)
        for checkbox in (self.trim_padding_check, self.center_canvas_check, self.outline_check):
            checkbox.toggled.connect(self._update_preview)
            controls_row.addWidget(checkbox)
        controls_row.addStretch(1)
        root.addLayout(controls_row)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.apply_button = QtWidgets.QPushButton("Save Polished Copy")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.apply_button)
        root.addLayout(button_row)

        self.before_preview.set_image(self.source_image)
        self._update_preview()

    def options(self) -> PolishOptions:
        return PolishOptions(
            clean_background=False,
            trim_padding=self.trim_padding_check.isChecked(),
            center_on_canvas=self.center_canvas_check.isChecked(),
            add_outline=self.outline_check.isChecked(),
        )

    def _clean_background(self) -> None:
        cleaned_image = call_with_busy(
            self,
            lambda: clean_background_with_ben2(self.working_image),
            message="Cleaning transparent background...",
            palette=self.app_palette,
        )
        if cleaned_image is None:
            return
        self.working_image = cleaned_image.convert("RGBA")
        self.clean_background_button.setText("Background Cleaned")
        self._update_preview()

    def _update_preview(self) -> None:
        self.polished_image = polish_image(self.working_image, self.options())
        self.after_preview.set_image(self.polished_image)


class _PreviewLabel(QtWidgets.QLabel):
    def __init__(self, caption: str, palette: dict, parent=None):
        super().__init__(parent)
        self._caption = caption
        self._image: Image.Image | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(260, 260)
        self.setText(caption)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {palette.get('image_loader_bg', '#3A3A3A')};
                border: 1px solid {palette.get('placeholder_border', '#555555')};
                color: {palette.get('label_color', '#A0A0A0')};
            }}
        """)

    def set_image(self, image: Image.Image) -> None:
        self._image = image.convert("RGBA")
        self._render()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render()

    def _render(self) -> None:
        if self._image is None:
            self.setText(self._caption)
            self.setPixmap(QtGui.QPixmap())
            return

        pixmap = _pixmap_from_image(self._image)
        available_size = self.size() - QtCore.QSize(12, 12)
        if available_size.width() > 0 and available_size.height() > 0:
            pixmap = pixmap.scaled(
                available_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self.setText("")
        self.setPixmap(pixmap)
        self.setToolTip(f"{self._caption}: {self._image.width}x{self._image.height}px")


def _pixmap_from_image(image: Image.Image) -> QtGui.QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QtGui.QImage(
        data,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QtGui.QImage.Format.Format_RGBA8888,
    )
    return QtGui.QPixmap.fromImage(qimage.copy())


__all__ = ["ImagePolishDialog"]

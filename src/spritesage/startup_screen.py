"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (C) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from PySide6 import QtCore, QtGui, QtWidgets


class StartupScreen(QtWidgets.QWidget):
    """Small progress window shown while the main application is starting."""

    def __init__(self, logo_path=None, palette=None):
        super().__init__(
            None,
            QtCore.Qt.WindowType.SplashScreen
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint,
        )
        self._palette = palette or {}

        self.setObjectName("StartupScreen")
        self.setFixedSize(460, 220)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(14)

        self.logo_label = QtWidgets.QLabel(self)
        self.logo_label.setFixedSize(56, 56)
        self.logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if logo_path:
            pixmap = QtGui.QPixmap(logo_path)
            if not pixmap.isNull():
                self.logo_label.setPixmap(
                    pixmap.scaled(
                        self.logo_label.size(),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )

        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setSpacing(4)
        title = QtWidgets.QLabel("Sprite Sage", self)
        title.setObjectName("StartupTitle")
        subtitle = QtWidgets.QLabel("Starting up", self)
        subtitle.setObjectName("StartupSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        header_layout.addWidget(self.logo_label)
        header_layout.addLayout(title_layout, 1)

        self.status_label = QtWidgets.QLabel("Preparing application...", self)
        self.status_label.setObjectName("StartupStatus")
        self.status_label.setWordWrap(True)

        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(12)

        layout.addLayout(header_layout)
        layout.addStretch(1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        self._apply_styles()

    def set_status(self, message, progress=None, busy=False):
        self.status_label.setText(message)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            if progress is not None:
                self.progress_bar.setValue(max(0, min(100, int(progress))))
        QtWidgets.QApplication.processEvents()

    def finish(self, main_window):
        self.set_status("Ready.", 100)
        self.close()
        main_window.activateWindow()

    def _apply_styles(self):
        window_bg = self._palette.get("window_bg", "#2B2B2B")
        widget_bg = self._palette.get("widget_bg", "#3C3F41")
        text_color = self._palette.get("text_color", "#BBBBBB")
        label_color = self._palette.get("label_color", "#909090")
        selected_bg = self._palette.get("tree_item_selected_bg", "#5A7E9E")
        border_color = self._palette.get("placeholder_border", "#555555")

        self.setStyleSheet(
            f"""
            QWidget#StartupScreen {{
                background-color: {window_bg};
                border: 1px solid {border_color};
            }}
            QLabel#StartupTitle {{
                color: #FFFFFF;
                font-size: 22px;
                font-weight: 600;
            }}
            QLabel#StartupSubtitle,
            QLabel#StartupStatus {{
                color: {text_color};
                font-size: 12px;
            }}
            QLabel#StartupSubtitle {{
                color: {label_color};
            }}
            QProgressBar {{
                background-color: {widget_bg};
                border: 1px solid {border_color};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {selected_bg};
                border-radius: 3px;
            }}
            """
        )


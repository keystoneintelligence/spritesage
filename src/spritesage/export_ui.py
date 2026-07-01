"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
from typing import Any, cast

from PySide6 import QtWidgets
from PySide6.QtWidgets import QMessageBox

from .config import build_application_stylesheet
from .utils import TextInputDialog


class GodotExportUiMixin:
    """Shared UI helpers for Godot export actions."""

    EXPORTS_DIRNAME = "exports"

    def _godot_export_project_directory(self) -> str:
        raise NotImplementedError

    def _resolve_godot_export_dir(self, folder_name: str) -> str:
        return os.path.join(
            self._godot_export_project_directory(),
            self.EXPORTS_DIRNAME,
            folder_name,
        )

    def _create_export_folder_dialog(self, default_name: str) -> TextInputDialog:
        return TextInputDialog(
            cast(QtWidgets.QWidget, self),
            title="Godot Export Folder",
            label_text="Folder name:",
            default_text=default_name,
            palette=cast(Any, self).app_palette,
        )

    def _prompt_for_export_folder_name(self, default_name: str) -> tuple[str, bool]:
        dialog = self._create_export_folder_dialog(default_name)
        result = dialog.exec()
        accepted = result == QtWidgets.QDialog.DialogCode.Accepted
        return dialog.textValue(), accepted

    def _show_export_message(self, icon: object, title: str, text: str) -> None:
        box = QMessageBox(cast(QtWidgets.QWidget, self))
        box.setIcon(cast(Any, icon))
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setStyleSheet(build_application_stylesheet(cast(Any, self).app_palette))
        box.exec()

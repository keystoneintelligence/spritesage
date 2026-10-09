"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import copy
import json
from pathlib import Path
from typing import Any, cast

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .theme import style_popup_dialog
from .utils import TextInputDialog
from .paths import export_directory
from .godot_export_transaction import ExportPlan
from .godot_export_review import friendly_changes
from .persistence import atomic_write


class GodotExportFolderDialog(TextInputDialog):
    """Keep the folder-name flow while allowing a direct Godot destination."""

    def __init__(
        self,
        parent,
        project_dir: str,
        default_name: str,
        palette: dict,
        remembered: str | None = None,
    ):
        super().__init__(
            parent,
            title="Godot Export Folder",
            label_text="Folder name:",
            default_text=default_name,
            palette=palette,
        )
        self.project_dir = project_dir
        self.custom_destination = remembered
        self.lineEdit().setEnabled(remembered is None)
        self.destination_edit = QtWidgets.QLineEdit(self)
        self.destination_edit.setReadOnly(True)
        self.destination_edit.setText(remembered or export_directory(project_dir, default_name))
        self.destination_edit.setToolTip(
            "Choose the actual Godot asset folder to preserve edits made in Godot."
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.destination_edit)
        browse = QtWidgets.QPushButton("Browse…", self)
        row.addWidget(browse)
        browse.clicked.connect(self._browse)
        reset = QtWidgets.QPushButton("Use project exports folder", self)
        reset.clicked.connect(self._use_project_exports)
        layout = cast(QtWidgets.QVBoxLayout, self.layout())
        layout.insertWidget(2, QtWidgets.QLabel("Export destination:", self))
        layout.insertLayout(3, row)
        layout.insertWidget(4, reset)
        self.lineEdit().textChanged.connect(self._update_default_destination)

    def _browse(self):
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose Godot asset folder", self.destination_edit.text()
        )
        if selected:
            self.custom_destination = str(Path(selected).resolve())
            self.destination_edit.setText(self.custom_destination)
            self.lineEdit().setEnabled(False)

    def _use_project_exports(self):
        self.custom_destination = None
        self.lineEdit().setEnabled(True)
        self._update_default_destination(self.textValue())

    def _update_default_destination(self, name: str):
        if self.custom_destination is None:
            try:
                self.destination_edit.setText(export_directory(self.project_dir, name.strip()))
            except ValueError:
                self.destination_edit.clear()

    def selected_directory(self) -> str | None:
        return self.custom_destination


class GodotExportUiMixin:
    """Shared UI helpers for Godot export actions."""

    EXPORTS_DIRNAME = "exports"

    def _godot_export_project_directory(self) -> str:
        raise NotImplementedError

    def _resolve_godot_export_dir(self, folder_name: str) -> str:
        default = export_directory(self._godot_export_project_directory(), folder_name)
        selected = getattr(self, "_godot_selected_destination", None)
        return str(Path(selected).resolve()) if selected else default

    def _godot_destination_preferences(self) -> Path:
        return Path(self._godot_export_project_directory()) / ".spritesage-godot-destinations.json"

    def _saved_godot_destinations(self) -> dict:
        try:
            value = json.loads(self._godot_destination_preferences().read_bytes())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _create_export_folder_dialog(self, default_name: str) -> GodotExportFolderDialog:
        saved = self._saved_godot_destinations().get(default_name)
        return GodotExportFolderDialog(
            cast(QtWidgets.QWidget, self),
            self._godot_export_project_directory(),
            default_name,
            cast(Any, self).app_palette,
            saved if isinstance(saved, str) and Path(saved).is_absolute() else None,
        )

    def _prompt_for_export_folder_name(self, default_name: str) -> tuple[str, bool]:
        self._godot_selected_destination = None
        self._godot_destination_key = default_name
        dialog = self._create_export_folder_dialog(default_name)
        result = dialog.exec()
        accepted = result == QtWidgets.QDialog.DialogCode.Accepted
        if accepted:
            self._godot_selected_destination = dialog.selected_directory()
        return dialog.textValue(), accepted

    def _remember_godot_destination(self):
        selected = getattr(self, "_godot_selected_destination", None)
        key = getattr(self, "_godot_destination_key", None)
        if key:
            saved = self._saved_godot_destinations()
            if selected:
                saved[key] = selected
            elif key in saved:
                del saved[key]
            else:
                return
            try:
                atomic_write(
                    self._godot_destination_preferences(),
                    json.dumps(saved, indent=2).encode("utf-8"),
                )
            except OSError as error:
                self._show_export_message(
                    QMessageBox.Icon.Warning,
                    "Godot Export",
                    f"Export succeeded, but the destination could not be remembered:\n{error}",
                )

    def _show_export_message(self, icon: object, title: str, text: str) -> None:
        box = QMessageBox(cast(QtWidgets.QWidget, self))
        box.setIcon(cast(Any, icon))
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        style_popup_dialog(box, cast(Any, self).app_palette)
        box.exec()

    def _confirm_godot_export(self, plan: ExportPlan) -> bool:
        if not plan.updates:
            return True
        box = QMessageBox(cast(QtWidgets.QWidget, self))
        box.setIcon(QMessageBox.Icon.Warning if plan.conflicts else QMessageBox.Icon.Question)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle("Update existing Godot assets?")
        box.setText("Are you sure the following Godot things will be updated?")
        details = "\n".join("\u2022 " + change for change in friendly_changes(plan.updates))
        if plan.creations:
            details += "\n\nNew assets:\n" + "\n".join(plan.creations)
        if plan.conflicts:
            details += (
                "\n\nChanged in both SpriteSage and Godot:\n"
                + "\n".join("• " + change for change in friendly_changes(plan.conflicts))
                + "\n\nExport will replace these Godot values with the listed SpriteSage values."
            )
        if plan.notices:
            details += "\n\nPreservation notes:\n" + "\n".join(plan.notices)
        details += "\n\nOnly the listed changes will be applied."
        complete_details = details
        lines = details.splitlines()
        if len(lines) > 32:
            details = (
                "\n".join(lines[:24])
                + "\n\nOpen Show Details to review the complete change list before exporting."
            )
        box.setInformativeText(details)
        if plan.file_diffs:
            box.setDetailedText(
                complete_details
                + "\n\nGodot resource changes:\n\n"
                + "\n\n".join(
                    value
                    for path, value in plan.file_diffs.items()
                    if path.suffix.lower() in (".tscn", ".tres")
                )
            )
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        button = box.button(QMessageBox.StandardButton.Ok)
        if button is not None:
            button.setText("Export")
        style_popup_dialog(box, cast(Any, self).app_palette)
        return box.exec() == QMessageBox.StandardButton.Ok

    def _run_godot_export(
        self, exporter, runner, *, project: bool = False, source_path: str | None = None
    ):
        """Review first, then process artwork and commit guarded candidate files."""
        document = Path(source_path) if source_path else None
        document_before = document.read_bytes() if document else None
        label = "Exporting Godot project" if project else "Exporting Godot sprite"
        options = {"progress_unit": "sprites"} if project else {}

        sprite_before = copy.deepcopy(getattr(exporter, "sprite_file", None))
        list_sources = getattr(exporter, "_sprite_paths", None)
        sources_before = list_sources() if callable(list_sources) else None

        def review(progress_callback=None):
            exporter.progress_callback = progress_callback
            return getattr(exporter, "review", exporter.prepare)()

        plan = runner(
            self,
            review,
            message="Reviewing Godot changes",
            progress_label=label,
            palette=cast(Any, self).app_palette,
            **options,
        )
        if plan is None:
            return None
        if document is not None:
            plan.guards[document] = document_before
        if plan.unchanged:
            self._remember_godot_destination()
            self._show_export_message(
                QMessageBox.Icon.Information,
                "Godot Export",
                "Godot assets are already up to date. No Godot assets were changed.",
            )
            return None
        if not self._confirm_godot_export(plan):
            return None

        def check_review():
            plan.check_guards()
            if getattr(exporter, "sprite_file", None) != sprite_before:
                raise ValueError(
                    "Sprite changed after the export preview. Export again to review it."
                )
            if (
                sources_before is not None
                and callable(list_sources)
                and list_sources() != sources_before
            ):
                raise ValueError(
                    "Project sprites changed after the export preview. Export again to review them."
                )

        def apply(progress_callback=None):
            check_review()
            exporter.progress_callback = progress_callback
            if plan.review_only:
                candidate = exporter.prepare()
                check_review()
                # Retain the original approval boundary through processing too.
                for path, expected in plan.guards.items():
                    if path in candidate.guards and candidate.guards[path] != expected:
                        raise ValueError(
                            "Files changed after the export preview. Export again to review them."
                        )
                    candidate.guards[path] = expected
            else:
                candidate = plan
            return candidate.apply(allow_conflicts=True)

        result = runner(
            self,
            apply,
            message="Processing and exporting Godot assets",
            progress_label=label,
            palette=cast(Any, self).app_palette,
            **options,
        )

        if result is not None:
            self._remember_godot_destination()
        return result

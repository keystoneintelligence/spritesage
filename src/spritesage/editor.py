"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import json
from datetime import datetime
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from .image_viewer import ImageViewerWidget
from .sage_editor import SageEditorView, SageFile
from .sprite_editor import SpriteEditorView
from .sprite_file import SpriteFile
from .config import MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT
from .undo_redo import UndoRedoState
from .persistence import damaged_path, recovery_path, restore_document, save_events

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}


class EditorWidget(QtWidgets.QWidget):
    undo_redo_state_changed = QtCore.Signal(object)
    recovery_available_changed = QtCore.Signal(bool)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self.current_file_path = None
        self.project_file_path = None
        self._save_states = {}
        self._recovery_file_path = None

        self.plain_text_editor = QtWidgets.QPlainTextEdit()
        self.plain_text_editor.setPlaceholderText(
            "Main Editor / Viewer Area\n\nUse 'File' menu or sidebar buttons\nto create or open a project."
        )
        self.plain_text_editor.setReadOnly(True)

        self.sage_editor = SageEditorView(self.app_palette)
        self.sage_editor.sprite_row_action.connect(self.load_file)
        self.sage_editor.undo_redo_state_changed.connect(self._emit_undo_redo_state)

        self.image_viewer = ImageViewerWidget(self.app_palette)

        self.sprite_editor = SpriteEditorView(self.app_palette)
        self.sprite_editor.return_to_sage.connect(self.load_file)
        self.sprite_editor.undo_redo_state_changed.connect(self._emit_undo_redo_state)
        self.sprite_editor.project_file_changed.connect(self._apply_project_change)

        self.stacked_layout = QtWidgets.QStackedLayout()
        self.stacked_layout.addWidget(self.plain_text_editor)
        self.stacked_layout.addWidget(self.sage_editor)
        self.stacked_layout.addWidget(self.image_viewer)
        self.stacked_layout.addWidget(self.sprite_editor)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        save_bar = QtWidgets.QHBoxLayout()
        self.save_status = QtWidgets.QLabel("No document open")
        self.save_status.setStyleSheet(f"color: {palette['text_color']}; padding: 6px;")
        self.save_status.setWordWrap(True)
        save_bar.addWidget(self.save_status)
        save_bar.addStretch()
        main_layout.addLayout(save_bar)
        main_layout.addLayout(self.stacked_layout)
        save_events.changed.connect(self._on_save_state)

        self.setMinimumSize(MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT)
        self._apply_styles()

    def undo_redo_state(self):
        current_widget = self.stacked_layout.currentWidget()
        if current_widget == self.sprite_editor:
            return self.sprite_editor.undo_redo_state()
        if current_widget == self.sage_editor:
            return self.sage_editor.undo_redo_state()
        return UndoRedoState()

    def _emit_undo_redo_state(self, *_args):
        self.undo_redo_state_changed.emit(self.undo_redo_state())

    def _on_save_state(self, path, state):
        path = os.path.normcase(os.path.abspath(path))
        self._save_states[path] = state
        if self._recovery_file_path and path == os.path.normcase(
            os.path.abspath(self._recovery_file_path)
        ):
            self._update_save_status()

    def _update_save_status(self):
        path = self._recovery_file_path
        available = bool(path and recovery_path(path).is_file())
        self.recovery_available_changed.emit(available)
        state = (
            self._save_states.get(os.path.normcase(os.path.abspath(path)), "Saved")
            if path
            else "No document open"
        )
        self.save_status.setText("Saved automatically" if state == "Saved" else state)
        self.save_status.setToolTip(
            f"{path}\nUse Undo/Redo for recent edits. File → Recover saved version… opens the saved checkpoint."
            if path
            else ""
        )

    def recover_saved_version(self):
        path = self._recovery_file_path
        if not path or not recovery_path(path).is_file():
            return
        previous_save_state = self._save_states.get(
            os.path.normcase(os.path.abspath(path)), "Saved"
        )
        try:
            checkpoint = recovery_path(path)
            data = json.loads(checkpoint.read_bytes())
            if not isinstance(data, dict):
                raise ValueError("The recovery checkpoint is not a JSON object.")
            saved_at = datetime.fromtimestamp(checkpoint.stat().st_mtime).astimezone()
            before_sage = before_sprite = recovered_sage = None
            sage = None
            preserve_damaged = False
            if path.lower().endswith(".sprite"):
                sage = self._ensure_sage_context()
                if sage is None:
                    raise ValueError("Open the sprite's project first.")
                SpriteFile.from_dict(data, sage.directory)
                try:
                    before_sprite = SpriteFile.from_json(path, sage.directory)
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    preserve_damaged = os.path.isfile(path)
                if (
                    self.current_file_path == path
                    and self.stacked_layout.currentWidget() == self.sprite_editor
                ):
                    before_sprite = self.sprite_editor._get_sprite_data_to_save()
            else:
                recovered_sage = SageFile.from_dict(data, path)
                try:
                    before_sage = SageFile.from_json(path)
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    preserve_damaged = os.path.isfile(path)
                if (
                    self.current_file_path == path
                    and self.stacked_layout.currentWidget() == self.sage_editor
                ):
                    before_sage = self.sage_editor.get_modified_sage_file()

            message = (
                f"Recover {os.path.basename(path)}?\n\n"
                f"Checkpoint saved: {saved_at:%Y-%m-%d %H:%M:%S %Z}\n"
                "This checkpoint preserves the file before its first edit in the session "
                "that created it, and is kept when Sprite Sage closes.\n\n"
                "Use Undo/Redo for recent edits."
            )
            if before_sage is not None or before_sprite is not None:
                message += "\nAfter recovery, use Edit → Undo to return to your current work."
            if preserve_damaged:
                message += f"\n\nA copy of the damaged file will be kept at:\n{damaged_path(path)}"
            reply = QtWidgets.QMessageBox.question(
                self,
                "Recover saved version",
                message,
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            restore_document(path, preserve_damaged=preserve_damaged)
            if before_sage is not None and recovered_sage is not None:
                self.current_file_path = self.project_file_path = path
                self.sage_editor.apply_external_change(
                    before_sage, recovered_sage, "Recover saved version"
                )
                self.stacked_layout.setCurrentWidget(self.sage_editor)
            elif before_sprite is not None and sage is not None:
                self.current_file_path = path
                self.sprite_editor.apply_recovered_file(path, sage, before_sprite)
                self.stacked_layout.setCurrentWidget(self.sprite_editor)
            else:
                self.load_file(path)
            self._emit_undo_redo_state()
            self._log_message(f"Recovered saved checkpoint: {path}")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            if previous_save_state.startswith("Save failed"):
                self._on_save_state(path, previous_save_state)
            QtWidgets.QMessageBox.warning(self, "Recovery failed", str(error))

    def _apply_project_change(self, before, after, label: str):
        self.current_file_path = after.filepath
        self.project_file_path = after.filepath
        self.sage_editor.apply_external_change(before, after, label)
        self.stacked_layout.setCurrentWidget(self.sage_editor)
        self._recovery_file_path = after.filepath
        self._update_save_status()
        self._emit_undo_redo_state()
        self._log_message(label)

    def _apply_styles(self):
        self.plain_text_editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {self.app_palette['widget_bg']};
                color: {self.app_palette['text_color']};
                border: 1px solid {self.app_palette['placeholder_border']};
                font-family: Consolas, Courier New, monospace;
            }}
        """)
        self.setStyleSheet(f"background-color: {self.app_palette['widget_bg']};")

    def load_file(self, file_path: str | None):
        if not self.finish_pending_save():
            return
        self.current_file_path = None
        self._recovery_file_path = (
            file_path
            if file_path and Path(file_path).suffix.lower() in {".sage", ".sprite"}
            else None
        )
        self._update_save_status()

        if not file_path:
            self.clear_editor()
            return

        if not os.path.isfile(file_path):
            if self._recovery_file_path:
                self._on_save_state(file_path, "Document missing")
            self.plain_text_editor.setPlainText("")
            self.plain_text_editor.setPlaceholderText("Selected item is not a file.")
            self.plain_text_editor.setReadOnly(True)
            self.stacked_layout.setCurrentWidget(self.plain_text_editor)
            self._emit_undo_redo_state()
            return

        _, extension = os.path.splitext(file_path.lower())

        self.current_file_path = file_path  # Set path before trying to load
        if extension == ".sage":
            try:
                self._load_sage_file(file_path)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self._handle_load_error(file_path, error)
        elif extension == ".sprite":
            self._load_sprite_file(file_path)
        elif extension in IMAGE_EXTENSIONS:
            self._load_image_file(file_path)
        else:
            self._load_text_file(file_path)
        if self.current_file_path and self._recovery_file_path:
            self._on_save_state(file_path, "Saved")

    def _read_file_content(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_sage_file(self, file_path: str):
        sage_file = SageFile.from_json(file_path)
        self.project_file_path = file_path
        self.sage_editor.load_data(sage_file)
        self.stacked_layout.setCurrentWidget(self.sage_editor)
        self._emit_undo_redo_state()
        self._log_message(f"Opened .sage file in custom editor: {file_path}")

    def _load_sprite_file(self, file_path: str):
        """Loads a .sprite file into the SpriteEditorView."""
        try:
            sage_file = self._ensure_sage_context()
            if sage_file is None:
                raise ValueError("Cannot load a sprite before a project file is loaded.")
            # Pass the path to the custom editor's loading method
            if self.sprite_editor.load_sprite_data(file_path, sage_file) is False:
                raise ValueError(
                    "The sprite could not be opened. A previous version may be available."
                )
            self.stacked_layout.setCurrentWidget(self.sprite_editor)
            self._emit_undo_redo_state()
            self._log_message(f"Opened .sprite file in custom editor: {file_path}")

        except Exception as e:
            # Use the generic error handler or create a specific one
            self._handle_load_error(file_path, e, "loading .sprite file")
            # Ensure state is reset on error
            self.current_file_path = None

    def set_project_file(self, project_file_path: str | None):
        self.project_file_path = project_file_path

    def _ensure_sage_context(self):
        sage_file = self.sage_editor.sage_file
        if sage_file is not None:
            return sage_file
        if not self.project_file_path or not os.path.isfile(self.project_file_path):
            return None

        sage_file = SageFile.from_json(self.project_file_path)
        self.sage_editor.load_data(sage_file)
        return self.sage_editor.sage_file

    def _load_image_file(self, file_path: str):
        """Loads an image file into the ImageViewerWidget."""
        try:
            success = self.image_viewer.load_image(file_path)
            if success:
                self.stacked_layout.setCurrentWidget(self.image_viewer)
                self._emit_undo_redo_state()
                self._log_message(f"Opened image file in viewer: {file_path}")
            else:
                raise ValueError("Image viewer failed to load the image.")
        except Exception as e:
            self._show_error_in_plaintext(f"Error displaying image file:\n{file_path}\n\n{e}")
            self._log_message(f"Error loading image {file_path}: {e}")
            self.current_file_path = None  # Indicate load failure

    def _load_text_file(self, file_path: str):
        try:
            content = self._read_file_content(file_path)
        except Exception as e:  # Catch read errors or load errors for text
            self._handle_load_error(file_path, e, "reading or loading text file")
            return
        self.plain_text_editor.setPlainText(content)
        self.plain_text_editor.setReadOnly(False)  # Allow editing non-sage files
        self.stacked_layout.setCurrentWidget(self.plain_text_editor)
        self._emit_undo_redo_state()
        # Log using the current_file_path which should have been set before calling
        self._log_message(f"Opened file: {self.current_file_path}")
        self.plain_text_editor.document().setModified(False)  # Reset modified state

    def _handle_load_error(self, file_path, error, context_message="loading file"):
        """Consolidated error handler for load failures."""
        error_display = f"Error {context_message}:\n{file_path}\n\n{error}"
        # Avoid trying to show raw content if the error was during reading itself
        self._show_error_in_plaintext(error_display)
        self._log_message(f"Error {context_message} {file_path}: {error}")
        self.current_file_path = None  # Indicate load failure
        self._on_save_state(file_path, "Could not open document")

    def _show_error_in_plaintext(self, error_message, raw_content=""):
        display_text = error_message
        if raw_content:
            display_text += "\n\n--- Raw File Content ---\n" + raw_content
        self.plain_text_editor.setPlainText(display_text)
        self.plain_text_editor.setReadOnly(True)
        self.stacked_layout.setCurrentWidget(self.plain_text_editor)
        self._emit_undo_redo_state()

    def clear_editor(self):
        if not self.finish_pending_save():
            return
        self.current_file_path = None
        self._recovery_file_path = None
        self._update_save_status()
        self.plain_text_editor.setPlainText("")
        self.plain_text_editor.setPlaceholderText("Select a valid file from the sidebar tree.")
        self.plain_text_editor.setReadOnly(True)
        self.stacked_layout.setCurrentWidget(self.plain_text_editor)
        self._emit_undo_redo_state()

    def finish_pending_save(self):
        if self.current_file_path:
            state = self._save_states.get(
                os.path.normcase(os.path.abspath(self.current_file_path)), ""
            )
            if state.startswith("Save failed") and self.save() is False:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Unsaved changes",
                    "The last save failed. Your edits are still open. Free disk space or check "
                    "file permissions, then save again before leaving this document.",
                )
                return False
        return True

    def _log_message(self, message):
        parent_widget = self.parent()
        while parent_widget:
            console_widget = getattr(parent_widget, "console_widget", None)
            log_message = getattr(console_widget, "log_message", None)
            if callable(log_message):
                log_message(message)
                return
            parent_widget = parent_widget.parent()
        print(f"LOG (Editor): {message}")

    def save(self):
        if not self.current_file_path:
            self._log_message("No file loaded to save.")
            return False

        current = self.stacked_layout.currentWidget()
        if current == self.sage_editor:
            return self.sage_editor.save()
        if current == self.sprite_editor:
            return self.sprite_editor.save()
        return True

    def undo(self):
        if self.stacked_layout.currentWidget() == self.sprite_editor:
            self.sprite_editor.undo()
        elif self.stacked_layout.currentWidget() == self.sage_editor:
            self.sage_editor.undo()
        else:
            print("No redo command found for the current widget")

    def redo(self):
        if self.stacked_layout.currentWidget() == self.sprite_editor:
            self.sprite_editor.redo()
        elif self.stacked_layout.currentWidget() == self.sage_editor:
            self.sage_editor.redo()
        else:
            print("No redo command found for the current widget")

    def export_project_to_godot(self):
        if self.sage_editor.sage_file is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Export Project",
                "Open a .sage project file before exporting the project.",
            )
            return
        self.sage_editor._export_project_to_godot()

    def export_sprite_to_godot(self):
        if self.stacked_layout.currentWidget() != self.sprite_editor:
            QtWidgets.QMessageBox.warning(
                self,
                "Export Sprite",
                "Open a .sprite file before exporting an individual sprite.",
            )
            return
        self.sprite_editor.export_current_sprite_to_godot()

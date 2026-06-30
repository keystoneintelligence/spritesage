"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
from PySide6 import QtWidgets

from .image_viewer import ImageViewerWidget
from .sage_editor import SageEditorView, SageFile
from .sprite_editor import SpriteEditorView
from .config import MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}


# --- EditorWidget (No changes needed here for this specific request) ---
class EditorWidget(QtWidgets.QWidget):

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self.current_file_path = None
        self.project_file_path = None

        self.plain_text_editor = QtWidgets.QPlainTextEdit()
        self.plain_text_editor.setPlaceholderText(
            "Main Editor / Viewer Area\n\nUse 'File' menu or sidebar buttons\nto create or open a project."
        )
        self.plain_text_editor.setReadOnly(True)

        self.sage_editor = SageEditorView(self.app_palette)
        self.sage_editor.sprite_row_action.connect(self.load_file)

        self.image_viewer = ImageViewerWidget(self.app_palette)

        self.sprite_editor = SpriteEditorView(self.app_palette)
        self.sprite_editor.return_to_sage.connect(self.load_file)

        self.stacked_layout = QtWidgets.QStackedLayout()
        self.stacked_layout.addWidget(self.plain_text_editor)
        self.stacked_layout.addWidget(self.sage_editor)
        self.stacked_layout.addWidget(self.image_viewer)
        self.stacked_layout.addWidget(self.sprite_editor)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(self.stacked_layout)

        self.setMinimumSize(MIN_EDITOR_CONSOLE_WIDTH, MIN_EDITOR_CONSOLE_HEIGHT)
        self._apply_styles()

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
        self.current_file_path = None

        if not file_path:
            self.clear_editor()
            return

        if not os.path.isfile(file_path):
            self.plain_text_editor.setPlainText("")
            self.plain_text_editor.setPlaceholderText("Selected item is not a file.")
            self.plain_text_editor.setReadOnly(True)
            self.stacked_layout.setCurrentWidget(self.plain_text_editor)
            return

        _, extension = os.path.splitext(file_path.lower())

        self.current_file_path = file_path  # Set path before trying to load
        if extension == ".sage":
            self._load_sage_file(file_path)
        elif extension == ".sprite":
            self._load_sprite_file(file_path)
        elif extension in IMAGE_EXTENSIONS:
            self._load_image_file(file_path)
        else:
            self._load_text_file(file_path)

    def _read_file_content(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_sage_file(self, file_path: str):
        sage_file = SageFile.from_json(file_path)
        self.project_file_path = file_path
        self.sage_editor.load_data(sage_file)
        self.stacked_layout.setCurrentWidget(self.sage_editor)
        self._log_message(f"Opened .sage file in custom editor: {file_path}")

    def _load_sprite_file(self, file_path: str):
        """Loads a .sprite file into the SpriteEditorView."""
        try:
            sage_file = self._ensure_sage_context()
            if sage_file is None:
                raise ValueError("Cannot load a sprite before a project file is loaded.")
            # Pass the path to the custom editor's loading method
            self.sprite_editor.load_sprite_data(file_path, sage_file)
            self.stacked_layout.setCurrentWidget(self.sprite_editor)
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

    def _show_error_in_plaintext(self, error_message, raw_content=""):
        display_text = error_message
        if raw_content:
            display_text += "\n\n--- Raw File Content ---\n" + raw_content
        self.plain_text_editor.setPlainText(display_text)
        self.plain_text_editor.setReadOnly(True)
        self.stacked_layout.setCurrentWidget(self.plain_text_editor)

    def clear_editor(self):
        self.plain_text_editor.setPlainText("")
        self.plain_text_editor.setPlaceholderText("Select a valid file from the sidebar tree.")
        self.plain_text_editor.setReadOnly(True)
        self.stacked_layout.setCurrentWidget(self.plain_text_editor)

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

        self.sage_editor.save()
        self.sprite_editor.save()

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

"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import json
import time
from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QMainWindow, QSplitter, QFileDialog, QMessageBox

# Import config
from .config import (
    EMPTY_SAGE_TEMPLATE,
    APP_PALETTE,
    SAGE_FILE_EXTENSION,
    SETTINGS_FILE_NAME,
    DEFAULT_SETTINGS,
    RECENT_PROJECTS_KEY,
)

# Import Menu Bar
from .menu_bar import AppMenuBar
from .ai_models import refresh_model_cache_for_settings
from .recent_projects import (
    add_recent_project,
    recent_projects_from_settings,
)

# Import Widgets (adjust path if you didn't add imports to widgets/__init__.py)
# Option 1: If widgets/__init__.py imports them
# from widgets import SidebarWidget, EditorWidget, LogoWidget, ConsoleWidget
# Option 2: Direct import (assuming main_window.py is in the parent dir of widgets/)
from .sidebar import SidebarWidget
from .editor import EditorWidget
from .sage_file import SageFile
from .logo import LogoWidget
from .console import ConsoleWidget


class MainWindow(QMainWindow):
    def __init__(self, logo_path=None, startup_progress=None):
        super().__init__()
        self._startup_progress = startup_progress or self._noop_startup_progress

        # --- Load or Create Settings File ---
        # Determine the path relative to the script file
        self._notify_startup("Loading settings...", 38)
        self.settings_file_path = SETTINGS_FILE_NAME
        self.settings = self._load_or_create_settings()
        self.recent_projects = recent_projects_from_settings(self.settings)
        self._notify_startup("Refreshing AI model list...", 48, busy=True)
        refresh_model_cache_for_settings(self.settings)
        self._notify_startup("Settings ready.", 60)
        # --- End Settings Loading ---

        self.active_palette = APP_PALETTE
        self.logo_path = logo_path
        self.current_project_path = None
        self.current_project_file = None
        self._startup_layout_sync_pending = True

        self.setWindowTitle("Modular Editor Interface (PySide6)")
        self.setGeometry(100, 100, 1000, 750)

        if self.logo_path and os.path.exists(self.logo_path):
            self.setWindowIcon(QtGui.QIcon(self.logo_path))
        else:
            print(f"Warning: Window icon not set. Logo file not found: {self.logo_path}")

        # --- Create Component Widgets ---
        # Pass self as parent so widgets can access main window if needed (e.g., console)
        self._notify_startup("Creating editor panels...", 68)
        self.console_widget = ConsoleWidget(palette=self.active_palette, parent=self)
        self.sidebar_widget = SidebarWidget(palette=self.active_palette, parent=self)
        self.editor_widget = EditorWidget(palette=self.active_palette, parent=self)
        self.logo_widget = LogoWidget(
            palette=self.active_palette, logo_path=self.logo_path, parent=self
        )

        # --- Setup Layout ---
        self._notify_startup("Arranging workspace...", 78)
        self._setup_layout()

        # --- Create Menu Bar and connect project signals ---
        self._notify_startup("Connecting application actions...", 84)
        self.app_menu_bar = AppMenuBar(
            self,
            settings_file_path=self.settings_file_path,
            initial_settings=self.settings,
        )
        self.app_menu_bar.update_recent_projects(self.recent_projects)
        self.app_menu_bar.new_project_requested.connect(self.project_new)
        self.app_menu_bar.open_project_requested.connect(self.project_open)
        self.app_menu_bar.open_recent_project_requested.connect(self.project_open_recent)
        self.app_menu_bar.save_project_requested.connect(self.project_save)
        self.app_menu_bar.export_project_requested.connect(
            self.editor_widget.export_project_to_godot
        )
        self.app_menu_bar.export_sprite_requested.connect(self.editor_widget.export_sprite_to_godot)
        self.app_menu_bar.undo_action.connect(self.editor_widget.undo)
        self.app_menu_bar.redo_action.connect(self.editor_widget.redo)
        self.editor_widget.undo_redo_state_changed.connect(self.app_menu_bar.set_undo_redo_state)
        self.app_menu_bar.set_undo_redo_state(self.editor_widget.undo_redo_state())
        self.setMenuBar(self.app_menu_bar)

        # --- Connect Sidebar Buttons ---
        self.sidebar_widget.new_project_requested.connect(self.project_new)
        self.sidebar_widget.load_project_requested.connect(self.project_open)
        self.sidebar_widget.recent_project_requested.connect(self.project_open_recent)

        # --- Connect Sidebar tree actions to Editor ---
        self.sidebar_widget.item_selected.connect(self._open_sidebar_item)
        self.sidebar_widget.file_renamed.connect(self._on_sidebar_file_renamed)
        self.sidebar_widget.file_deleted.connect(self._on_sidebar_file_deleted)

        # --- Apply Initial Sizes/Stretch Factors & Sync ---
        self._set_initial_sizes()
        self._apply_main_styles()
        self.inner_splitter.splitterMoved.connect(self.sync_bottom_splitter_size)
        self.bottom_splitter.splitterMoved.connect(self.sync_top_splitter_size)

        # --- Initial State ---
        self._update_window_title()
        self.sidebar_widget.update_recent_projects(self.recent_projects)
        self.sidebar_widget.show_initial_view()  # Ensure sidebar starts with buttons
        self._notify_startup("Workspace ready.", 92)

    @staticmethod
    def _noop_startup_progress(message, progress=None, busy=False):
        pass

    def _notify_startup(self, message, progress=None, busy=False):
        self._startup_progress(message, progress, busy)

    def _load_or_create_settings(self) -> dict:
        """Loads settings from .sagesettings or creates it with defaults."""
        settings = DEFAULT_SETTINGS.copy()  # Start with defaults
        if os.path.exists(self.settings_file_path):
            try:
                with open(self.settings_file_path, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                # Update defaults with loaded settings (preserves defaults if keys missing)
                settings.update(loaded_settings)
                settings[RECENT_PROJECTS_KEY] = recent_projects_from_settings(settings)
                print(f"Loaded settings from: {self.settings_file_path}")
            except (json.JSONDecodeError, OSError) as e:
                print(
                    f"Error loading settings file '{self.settings_file_path}': {e}. Using defaults."
                )
                # If loading fails, we just stick with the defaults defined above
        else:
            print(f"Settings file not found. Creating '{self.settings_file_path}' with defaults.")
            try:
                with open(self.settings_file_path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=4)
            except OSError as e:
                print(
                    f"Error creating settings file '{self.settings_file_path}': {e}. Using in-memory defaults."
                )
                # If creation fails, keep using the in-memory defaults
        return settings

    def _save_settings(self):
        try:
            with open(self.settings_file_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except OSError as e:
            self.console_widget.log_message(f"Error saving settings file: {e}")

    def _setup_layout(self):
        self.outer_splitter = QSplitter(QtCore.Qt.Orientation.Vertical, self)
        self.inner_splitter = QSplitter(QtCore.Qt.Orientation.Horizontal, self.outer_splitter)
        self.bottom_splitter = QSplitter(QtCore.Qt.Orientation.Horizontal, self.outer_splitter)
        self.inner_splitter.addWidget(self.sidebar_widget)
        self.inner_splitter.addWidget(self.editor_widget)
        self.inner_splitter.setCollapsible(0, False)
        self.inner_splitter.setCollapsible(1, False)
        self.bottom_splitter.addWidget(self.logo_widget)
        self.bottom_splitter.addWidget(self.console_widget)
        self.bottom_splitter.setCollapsible(0, False)
        self.bottom_splitter.setCollapsible(1, False)
        self.outer_splitter.addWidget(self.inner_splitter)
        self.outer_splitter.addWidget(self.bottom_splitter)
        self.outer_splitter.setCollapsible(0, False)
        self.outer_splitter.setCollapsible(1, False)
        self.setCentralWidget(self.outer_splitter)

    def showEvent(self, event: QtGui.QShowEvent):
        super().showEvent(event)
        if self._startup_layout_sync_pending:
            self._startup_layout_sync_pending = False
            QtCore.QTimer.singleShot(0, self.initial_sync)

    def _update_window_title(self):
        base_title = "Modular Editor Interface (PySide6)"
        if self.current_project_path:
            project_name = os.path.basename(self.current_project_path)
            self.setWindowTitle(f"{project_name} - {base_title}")
        else:
            self.setWindowTitle(base_title)

    # --- Project Handling Methods ---

    def project_new(self):
        self.console_widget.log_message("Initiating New Project...")
        start_dir = os.getcwd()
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select New Project Folder",
            start_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )

        if not dir_path:
            self.console_widget.log_message("New project creation cancelled.")
            return

        project_name = os.path.basename(dir_path)
        sage_file_path = os.path.join(dir_path, project_name + SAGE_FILE_EXTENSION)

        if os.path.exists(sage_file_path):
            reply = QMessageBox.question(
                self,
                "Project Exists",
                f"A project file '{os.path.basename(sage_file_path)}' already exists.\nOpen it instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._load_project(dir_path, sage_file_path)
            else:
                self.console_widget.log_message("New project cancelled: File exists.")
            return

        # Note: Project file still contains these keys, but they might be overridden
        # or ignored in favour of the global .sagesettings values depending on logic.
        # Consider if these should be removed from project metadata eventually.
        default_metadata = EMPTY_SAGE_TEMPLATE.copy()
        default_metadata["Project Name"] = project_name
        default_metadata["createdAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            with open(sage_file_path, "w", encoding="utf-8") as f:
                json.dump(default_metadata, f, indent=4)
            self.console_widget.log_message(f"Created project file: {sage_file_path}")
            self._load_project(dir_path, sage_file_path)
        except OSError as e:
            error_msg = f"Error creating project file: {e}"
            self.console_widget.log_message(error_msg)
            QMessageBox.critical(self, "Project Creation Error", error_msg)

    def project_open(self):
        self.console_widget.log_message("Initiating Open Project...")
        sage_filter = f"Sage Project Files (*{SAGE_FILE_EXTENSION});;All Files (*)"
        start_dir = os.getcwd()
        sage_file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Sage Project File", start_dir, sage_filter
        )

        if not sage_file_path:
            self.console_widget.log_message("Project open cancelled.")
            return

        if not sage_file_path.lower().endswith(SAGE_FILE_EXTENSION):
            error_msg = f"Selected file is not a valid project file ({SAGE_FILE_EXTENSION}):\n{sage_file_path}"
            self.console_widget.log_message(error_msg)
            QMessageBox.warning(self, "Open Project Error", error_msg)
            return

        project_dir = os.path.dirname(sage_file_path)
        self._load_project(project_dir, sage_file_path)

    def project_open_recent(self, sage_file_path: str):
        self.console_widget.log_message(f"Opening recent project: {sage_file_path}")
        if not sage_file_path.lower().endswith(SAGE_FILE_EXTENSION):
            error_msg = (
                f"Recent project is not a valid project file ({SAGE_FILE_EXTENSION}):\n"
                f"{sage_file_path}"
            )
            self.console_widget.log_message(error_msg)
            QMessageBox.warning(self, "Open Recent Project Error", error_msg)
            return
        if not os.path.isfile(sage_file_path) or not os.access(sage_file_path, os.R_OK):
            error_msg = f"Recent project file could not be opened:\n{sage_file_path}"
            self.console_widget.log_message(error_msg)
            QMessageBox.warning(self, "Open Recent Project Error", error_msg)
            return

        self._load_project(os.path.dirname(sage_file_path), sage_file_path)

    def project_save(self):
        if not self.current_project_file or not self.current_project_path:
            self.console_widget.log_message("Save Project: No project is currently open.")
            return
        self.editor_widget.save()
        self.console_widget.log_message(f"Saving project metadata to: {self.current_project_file}")
        try:
            metadata = {}
            if os.path.exists(self.current_project_file):
                with open(self.current_project_file, "r", encoding="utf-8") as f:
                    try:
                        metadata = json.load(f)
                    except json.JSONDecodeError:
                        self.console_widget.log_message(
                            f"Warning: Could not parse {self.current_project_file}. Overwriting."
                        )
                        metadata = {}
            metadata["lastSaved"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(self.current_project_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)
            self.console_widget.log_message("Project metadata saved successfully.")
        except (OSError, json.JSONDecodeError) as e:
            error_msg = f"Error saving project file: {e}"
            self.console_widget.log_message(error_msg)
            QMessageBox.critical(self, "Project Save Error", error_msg)

    def _load_project(self, project_dir, sage_file):
        """Internal helper to load project data and update UI components."""
        self.console_widget.log_message(f"Loading project from: {project_dir}")
        project_metadata = {}  # Default to empty if load fails
        try:
            # Check if file exists and is readable before opening
            if not os.access(project_dir, os.R_OK):
                raise OSError(f"Cannot read project directory: {project_dir}")
            if not os.access(sage_file, os.R_OK):
                raise OSError(f"Cannot read project file: {sage_file}")

            with open(sage_file, "r", encoding="utf-8") as f:
                project_metadata = json.load(f)
            project_name = project_metadata.get(
                "Project Name", os.path.basename(project_dir)
            )  # Use metadata name if available
            self.console_widget.log_message(f"Project '{project_name}' metadata loaded.")
        except (OSError, json.JSONDecodeError, FileNotFoundError) as e:
            error_msg = (
                f"Error reading project file {sage_file}: {e}. Proceeding with directory view."
            )
            self.console_widget.log_message(error_msg)
            # Optionally show a warning to the user
            # QMessageBox.warning(self, "Project Load Warning", error_msg)
            # Reset metadata to avoid issues later if the file was corrupt
            project_metadata = {}  # Ensure metadata is empty on error

        # --- Update State ---
        self.current_project_path = project_dir
        self.current_project_file = sage_file  # Still store path even if read failed
        self.editor_widget.set_project_file(sage_file)

        # --- Update UI ---
        self.sidebar_widget.set_project(self.current_project_path)
        self.app_menu_bar.set_project_actions_enabled(True)
        self._update_window_title()
        # Load the .sage file into the editor if it was successfully read, otherwise clear editor
        if project_metadata:
            self.editor_widget.load_file(sage_file)
        else:
            self.editor_widget.clear_editor()  # Or load blank state

        self.console_widget.log_message("Project loaded.")

        self._remember_recent_project(project_dir, sage_file, project_metadata)

    def _remember_recent_project(self, project_dir: str, sage_file: str, project_metadata: dict):
        project_name = project_metadata.get("Project Name") if project_metadata else None
        self.recent_projects = add_recent_project(
            self.recent_projects,
            project_dir,
            sage_file,
            project_name,
        )
        self.settings[RECENT_PROJECTS_KEY] = self.recent_projects
        self.sidebar_widget.update_recent_projects(self.recent_projects)
        self.app_menu_bar.update_recent_projects(self.recent_projects)
        self.app_menu_bar.current_app_settings[RECENT_PROJECTS_KEY] = self.recent_projects
        self._save_settings()

    def _open_sidebar_item(self, file_path: str):
        if not file_path:
            self.editor_widget.clear_editor()
            return

        self.editor_widget.set_project_file(self.current_project_file)
        self.editor_widget.load_file(file_path)

    def _on_sidebar_file_renamed(self, old_path: str, new_path: str):
        self._remap_open_paths(old_path, new_path)
        self._refresh_editor_after_file_change(new_path)
        self.console_widget.log_message(f"Renamed: {old_path} -> {new_path}")

    def _on_sidebar_file_deleted(self, deleted_path: str):
        if deleted_path.lower().endswith(".sprite") and os.path.isfile(deleted_path):
            self._hide_sprite_file_from_project(deleted_path)
            if self._path_contains(deleted_path, self.editor_widget.current_file_path):
                if self.current_project_file and os.path.isfile(self.current_project_file):
                    self.editor_widget.load_file(self.current_project_file)
                else:
                    self.editor_widget.clear_editor()
            else:
                self._refresh_editor_after_file_change(None)
            self.console_widget.log_message(f"Removed sprite from project: {deleted_path}")
            return

        deleted_current_file = self._path_contains(
            deleted_path, self.editor_widget.current_file_path
        )
        deleted_project_file = self._path_contains(deleted_path, self.current_project_file)

        if deleted_project_file:
            self.current_project_file = None
            self.editor_widget.set_project_file(None)

        if deleted_current_file:
            if self.current_project_file and os.path.isfile(self.current_project_file):
                self.editor_widget.load_file(self.current_project_file)
            else:
                self.editor_widget.clear_editor()
        else:
            self._refresh_editor_after_file_change(None)

        self.console_widget.log_message(f"Deleted: {deleted_path}")

    def _hide_sprite_file_from_project(self, sprite_path: str):
        if not self.current_project_path or not self.current_project_file:
            return
        try:
            relative_path = os.path.relpath(sprite_path, self.current_project_path).replace(
                "\\", "/"
            )
        except ValueError:
            return
        try:
            sage_file = SageFile.from_json(self.current_project_file)
        except Exception as e:
            self.console_widget.log_message(f"Could not update project sprite list: {e}")
            return

        hidden_sprites = {path.replace("\\", "/") for path in sage_file.hidden_sprites}
        hidden_sprites.add(relative_path)
        sage_file.hidden_sprites = sorted(hidden_sprites)
        sage_file.save()
        self.editor_widget.sage_editor.sage_file = sage_file

    def _remap_open_paths(self, old_path: str, new_path: str):
        remapped_project_file = self._remap_path(self.current_project_file, old_path, new_path)
        if remapped_project_file != self.current_project_file:
            self.current_project_file = remapped_project_file
            self.editor_widget.set_project_file(remapped_project_file)
            if self.current_project_path and remapped_project_file:
                project_metadata = {}
                try:
                    with open(remapped_project_file, "r", encoding="utf-8") as f:
                        project_metadata = json.load(f)
                except (OSError, json.JSONDecodeError):
                    project_metadata = {}
                self._remember_recent_project(
                    self.current_project_path,
                    remapped_project_file,
                    project_metadata,
                )

        remapped_editor_file = self._remap_path(
            self.editor_widget.current_file_path, old_path, new_path
        )
        if remapped_editor_file != self.editor_widget.current_file_path and remapped_editor_file:
            self.editor_widget.load_file(remapped_editor_file)

    def _refresh_editor_after_file_change(self, preferred_path: str | None):
        current_path = self.editor_widget.current_file_path
        if (
            preferred_path
            and current_path
            and os.path.abspath(preferred_path) == os.path.abspath(current_path)
        ):
            return

        current_widget = self.editor_widget.stacked_layout.currentWidget()
        if (
            current_widget == self.editor_widget.sage_editor
            and self.current_project_file
            and os.path.isfile(self.current_project_file)
        ):
            self.editor_widget.load_file(self.current_project_file)
            return

        sage_file = self.editor_widget.sage_editor.sage_file
        if (
            sage_file is not None
            and self.current_project_file
            and os.path.isfile(self.current_project_file)
        ):
            try:
                self.editor_widget.sage_editor.load_data(
                    SageFile.from_json(self.current_project_file)
                )
            except Exception as e:
                self.console_widget.log_message(f"Could not refresh project view: {e}")

    @staticmethod
    def _remap_path(path: str | None, old_path: str, new_path: str) -> str | None:
        if not path:
            return path
        path_abs = os.path.abspath(path)
        old_abs = os.path.abspath(old_path)
        new_abs = os.path.abspath(new_path)
        if path_abs == old_abs:
            return new_abs
        try:
            if os.path.commonpath([path_abs, old_abs]) == old_abs:
                return os.path.join(new_abs, os.path.relpath(path_abs, old_abs))
        except ValueError:
            return path
        return path

    @staticmethod
    def _path_contains(container_path: str, candidate_path: str | None) -> bool:
        if not candidate_path:
            return False
        container_abs = os.path.abspath(container_path)
        candidate_abs = os.path.abspath(candidate_path)
        try:
            return os.path.commonpath([container_abs, candidate_abs]) == container_abs
        except ValueError:
            return False

    # --- UI Styling and Themeing ---

    def _apply_main_styles(self):
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {self.active_palette['window_bg']}; }}"
        )
        splitter_style = f"""
            QSplitter::handle {{
                background-color: {self.active_palette['splitter_handle']};
            }}
            QSplitter::handle:horizontal {{
                height: 5px; /* Adjust thickness */
                margin: 0px 2px; /* Optional spacing */
            }}
            QSplitter::handle:vertical {{
                width: 5px;  /* Adjust thickness */
                margin: 2px 0px; /* Optional spacing */
            }}
            QSplitter::handle:pressed {{
                background-color: {QtGui.QColor(self.active_palette['splitter_handle']).lighter(120).name()};
            }}
        """
        self.outer_splitter.setStyleSheet(splitter_style)
        # Apply to inner splitters too if they should have the same style
        self.inner_splitter.setStyleSheet(splitter_style)
        self.bottom_splitter.setStyleSheet(splitter_style)

    def _set_initial_sizes(self):
        # Outer: Top (inner+editor) vs Bottom (logo+console)
        self.outer_splitter.setSizes([500, 250])  # Example: give top more space initially
        self.outer_splitter.setStretchFactor(0, 3)
        self.outer_splitter.setStretchFactor(1, 1)

        # Inner: Sidebar vs Editor
        self.inner_splitter.setSizes([250, 750])  # Example: give editor more space
        self.inner_splitter.setStretchFactor(0, 1)
        self.inner_splitter.setStretchFactor(1, 4)

        # Bottom: Logo vs Console
        self.bottom_splitter.setSizes([250, 750])  # Sync with inner initial ratio
        self.bottom_splitter.setStretchFactor(0, 1)
        self.bottom_splitter.setStretchFactor(1, 4)

    def initial_sync(self):
        # Sync bottom splitter to match inner splitter's initial state *after* layout is shown
        sizes = self.inner_splitter.sizes()
        if sizes and len(sizes) == 2 and sum(sizes) > 0:
            self.bottom_splitter.blockSignals(True)
            self.bottom_splitter.setSizes(sizes)
            self.bottom_splitter.blockSignals(False)
            # Force logo resize calculation after splitter is set
            self.logo_widget.resizeEvent(
                QtGui.QResizeEvent(self.logo_widget.size(), self.logo_widget.size())
            )

    def sync_bottom_splitter_size(self, pos, index):
        # When inner_splitter (sidebar/editor) is resized, sync bottom_splitter (logo/console)
        # Check if the splitter causing the signal is the one we expect
        if self.sender() is self.inner_splitter:
            sizes = self.inner_splitter.sizes()
            if sizes and len(sizes) == 2 and sum(sizes) > 0:
                self.bottom_splitter.blockSignals(True)
                self.bottom_splitter.setSizes(sizes)
                self.bottom_splitter.blockSignals(False)

    def sync_top_splitter_size(self, pos, index):
        # When bottom_splitter (logo/console) is resized, sync inner_splitter (sidebar/editor)
        if self.sender() is self.bottom_splitter:
            sizes = self.bottom_splitter.sizes()
            if sizes and len(sizes) == 2 and sum(sizes) > 0:
                self.inner_splitter.blockSignals(True)
                self.inner_splitter.setSizes(sizes)
                self.inner_splitter.blockSignals(False)

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Add any cleanup or save prompts here if needed
        # For example, you might want to save the current settings back to the file
        # self._save_settings() # Optional: Implement this if settings can change run-time
        event.accept()

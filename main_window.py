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
from config import EMPTY_SAGE_TEMPLATE, APP_PALETTE, SAGE_FILE_EXTENSION, SETTINGS_FILE_NAME, DEFAULT_SETTINGS

# Import utils
from utils import ProjectFileError # Example, though not used directly here

# Import Menu Bar
from menu_bar import AppMenuBar

# Import Widgets (adjust path if you didn't add imports to widgets/__init__.py)
# Option 1: If widgets/__init__.py imports them
# from widgets import SidebarWidget, EditorWidget, LogoWidget, ConsoleWidget
# Option 2: Direct import (assuming main_window.py is in the parent dir of widgets/)
from sidebar import SidebarWidget
from editor import EditorWidget
from logo import LogoWidget
from console import ConsoleWidget


class MainWindow(QMainWindow):
    def __init__(self, logo_path=None):
        super().__init__()

        # --- Load or Create Settings File ---
        # Determine the path relative to the script file
        self.settings_file_path = SETTINGS_FILE_NAME
        self.settings = self._load_or_create_settings()
        # --- End Settings Loading ---

        self.active_palette = APP_PALETTE
        self.logo_path = logo_path
        self.current_project_path = None
        self.current_project_file = None

        self.setWindowTitle("Modular Editor Interface (PySide6)")
        self.setGeometry(100, 100, 1000, 750)

        if self.logo_path and os.path.exists(self.logo_path):
            self.setWindowIcon(QtGui.QIcon(self.logo_path))
        else:
            print(f"Warning: Window icon not set. Logo file not found: {self.logo_path}")

        # --- Create Component Widgets ---
        # Pass self as parent so widgets can access main window if needed (e.g., console)
        self.console_widget = ConsoleWidget(palette=self.active_palette, parent=self)
        self.sidebar_widget = SidebarWidget(palette=self.active_palette, parent=self)
        self.editor_widget = EditorWidget(palette=self.active_palette, parent=self)
        self.logo_widget = LogoWidget(palette=self.active_palette, logo_path=self.logo_path, parent=self)

        # --- Setup Layout ---
        self._setup_layout()

        # --- Create Menu Bar and connect project signals ---
        self.app_menu_bar = AppMenuBar(self)
        self.app_menu_bar.new_project_requested.connect(self.project_new)
        self.app_menu_bar.open_project_requested.connect(self.project_open)
        self.app_menu_bar.save_project_requested.connect(self.project_save)
        self.app_menu_bar.undo_action.connect(self.editor_widget.undo)
        self.app_menu_bar.redo_action.connect(self.editor_widget.redo)
        self.setMenuBar(self.app_menu_bar)

        # --- Connect Sidebar Buttons ---
        self.sidebar_widget.new_project_requested.connect(self.project_new)
        self.sidebar_widget.load_project_requested.connect(self.project_open)

        # --- Connect Sidebar tree selection to Editor ---
        self.sidebar_widget.item_selected.connect(self.editor_widget.load_file)

        # --- Apply Initial Sizes/Stretch Factors & Sync ---
        self._set_initial_sizes()
        self._apply_main_styles()
        self.inner_splitter.splitterMoved.connect(self.sync_bottom_splitter_size)
        self.bottom_splitter.splitterMoved.connect(self.sync_top_splitter_size)
        QtCore.QTimer.singleShot(0, self.initial_sync) # Sync after layout is stable

        # --- Initial State ---
        self._update_window_title()
        self.sidebar_widget.show_initial_view() # Ensure sidebar starts with buttons

    def _load_or_create_settings(self) -> dict:
        """Loads settings from .sagesettings or creates it with defaults."""
        settings = DEFAULT_SETTINGS.copy() # Start with defaults
        if os.path.exists(self.settings_file_path):
            try:
                with open(self.settings_file_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                # Update defaults with loaded settings (preserves defaults if keys missing)
                settings.update(loaded_settings)
                print(f"Loaded settings from: {self.settings_file_path}")
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error loading settings file '{self.settings_file_path}': {e}. Using defaults.")
                # If loading fails, we just stick with the defaults defined above
        else:
            print(f"Settings file not found. Creating '{self.settings_file_path}' with defaults.")
            try:
                with open(self.settings_file_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=4)
            except OSError as e:
                print(f"Error creating settings file '{self.settings_file_path}': {e}. Using in-memory defaults.")
                # If creation fails, keep using the in-memory defaults
        return settings

    def _setup_layout(self):
        self.outer_splitter = QSplitter(QtCore.Qt.Orientation.Vertical, self)
        self.inner_splitter = QSplitter(QtCore.Qt.Orientation.Horizontal, self.outer_splitter)
        self.bottom_splitter = QSplitter(QtCore.Qt.Orientation.Horizontal, self.outer_splitter)
        self.inner_splitter.addWidget(self.sidebar_widget)
        self.inner_splitter.addWidget(self.editor_widget)
        self.inner_splitter.setCollapsible(0, False); self.inner_splitter.setCollapsible(1, False)
        self.bottom_splitter.addWidget(self.logo_widget)
        self.bottom_splitter.addWidget(self.console_widget)
        self.bottom_splitter.setCollapsible(0, False); self.bottom_splitter.setCollapsible(1, False)
        self.outer_splitter.addWidget(self.inner_splitter)
        self.outer_splitter.addWidget(self.bottom_splitter)
        self.outer_splitter.setCollapsible(0, False); self.outer_splitter.setCollapsible(1, False)
        self.setCentralWidget(self.outer_splitter)

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
            self, "Select New Project Folder", start_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )

        if not dir_path:
            self.console_widget.log_message("New project creation cancelled.")
            return

        project_name = os.path.basename(dir_path)
        sage_file_path = os.path.join(dir_path, project_name + SAGE_FILE_EXTENSION)

        if os.path.exists(sage_file_path):
             reply = QMessageBox.question(self, 'Project Exists', f"A project file '{os.path.basename(sage_file_path)}' already exists.\nOpen it instead?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.Yes:
                 self._load_project(dir_path, sage_file_path)
             else:
                 self.console_widget.log_message(f"New project cancelled: File exists.")
             return

        # Note: Project file still contains these keys, but they might be overridden
        # or ignored in favour of the global .sagesettings values depending on logic.
        # Consider if these should be removed from project metadata eventually.
        default_metadata = EMPTY_SAGE_TEMPLATE.copy()
        default_metadata["Project Name"] = project_name
        default_metadata["createdAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            with open(sage_file_path, 'w', encoding='utf-8') as f:
                json.dump(default_metadata, f, indent=4)
            self.console_widget.log_message(f"Created project file: {sage_file_path}")
            self._load_project(dir_path, sage_file_path)
        except OSError as e:
            error_msg = f"Error creating project file: {e}"; self.console_widget.log_message(error_msg); QMessageBox.critical(self, "Project Creation Error", error_msg)

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
             error_msg = f"Selected file is not a valid project file ({SAGE_FILE_EXTENSION}):\n{sage_file_path}"; self.console_widget.log_message(error_msg); QMessageBox.warning(self, "Open Project Error", error_msg)
             return

        project_dir = os.path.dirname(sage_file_path)
        self._load_project(project_dir, sage_file_path)

    def project_save(self):
        if not self.current_project_file or not self.current_project_path:
            self.console_widget.log_message("Save Project: No project is currently open.")
            return
        self.editor_widget.save()
        self.console_widget.log_message(f"Saving project metadata to: {self.current_project_file}")
        try:
            metadata = {}
            if os.path.exists(self.current_project_file):
                with open(self.current_project_file, 'r', encoding='utf-8') as f:
                    try: metadata = json.load(f)
                    except json.JSONDecodeError: self.console_widget.log_message(f"Warning: Could not parse {self.current_project_file}. Overwriting."); metadata = {}
            metadata['lastSaved'] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(self.current_project_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4)
            self.console_widget.log_message("Project metadata saved successfully.")
        except (OSError, json.JSONDecodeError) as e:
             error_msg = f"Error saving project file: {e}"; self.console_widget.log_message(error_msg); QMessageBox.critical(self, "Project Save Error", error_msg)

    def _load_project(self, project_dir, sage_file):
        """ Internal helper to load project data and update UI components. """
        self.console_widget.log_message(f"Loading project from: {project_dir}")
        project_metadata = {} # Default to empty if load fails
        try:
            # Check if file exists and is readable before opening
            if not os.access(project_dir, os.R_OK):
                 raise OSError(f"Cannot read project directory: {project_dir}")
            if not os.access(sage_file, os.R_OK):
                 raise OSError(f"Cannot read project file: {sage_file}")

            with open(sage_file, 'r', encoding='utf-8') as f:
                project_metadata = json.load(f)
            project_name = project_metadata.get("Project Name", os.path.basename(project_dir)) # Use metadata name if available
            self.console_widget.log_message(f"Project '{project_name}' metadata loaded.")
        except (OSError, json.JSONDecodeError, FileNotFoundError) as e:
             error_msg = f"Error reading project file {sage_file}: {e}. Proceeding with directory view."; self.console_widget.log_message(error_msg)
             # Optionally show a warning to the user
             # QMessageBox.warning(self, "Project Load Warning", error_msg)
             # Reset metadata to avoid issues later if the file was corrupt
             project_metadata = {} # Ensure metadata is empty on error

        # --- Update State ---
        self.current_project_path = project_dir
        self.current_project_file = sage_file # Still store path even if read failed

        # --- Update UI ---
        self.sidebar_widget.set_project(self.current_project_path)
        self.app_menu_bar.set_project_actions_enabled(True)
        self._update_window_title()
        # Load the .sage file into the editor if it was successfully read, otherwise clear editor
        if project_metadata:
             self.editor_widget.load_file(sage_file)
        else:
             self.editor_widget.clear_editor() # Or load blank state

        self.console_widget.log_message("Project loaded.")

    # --- UI Styling and Themeing ---

    def _apply_main_styles(self):
        self.setStyleSheet(f"QMainWindow {{ background-color: {self.active_palette['window_bg']}; }}")
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
        self.outer_splitter.setSizes([500, 250]) # Example: give top more space initially
        self.outer_splitter.setStretchFactor(0, 3)
        self.outer_splitter.setStretchFactor(1, 1)

        # Inner: Sidebar vs Editor
        self.inner_splitter.setSizes([250, 750]) # Example: give editor more space
        self.inner_splitter.setStretchFactor(0, 1)
        self.inner_splitter.setStretchFactor(1, 4)

        # Bottom: Logo vs Console
        self.bottom_splitter.setSizes([250, 750]) # Sync with inner initial ratio
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
            self.logo_widget.resizeEvent(QtGui.QResizeEvent(self.logo_widget.size(), self.logo_widget.size()))

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

"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import json
from PySide6 import QtWidgets, QtGui
from PySide6.QtCore import Signal

from inference import AIModel
from config import SETTINGS_FILE_NAME


class SettingsDialog(QtWidgets.QDialog):
    """
    A dialog window for configuring application settings like API keys and inference model.
    """
    # Signal emitted when settings are saved, passing the new settings dictionary
    settings_saved = Signal(dict)

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(450) # Adjust as needed

        self.current_settings = current_settings

        # --- Widgets ---
        self.openai_api_key_input = QtWidgets.QLineEdit()
        self.openai_api_key_input.setEchoMode(QtWidgets.QLineEdit.Password)

        self.google_api_key_input = QtWidgets.QLineEdit()
        self.google_api_key_input.setEchoMode(QtWidgets.QLineEdit.Password)

        self.inference_label = QtWidgets.QLabel("Selected Inference")
        self.inference_button_group = QtWidgets.QButtonGroup(self)
        self.inference_radio_buttons = {} # Store radio buttons for easy access

        self.save_button = QtWidgets.QPushButton("Save")
        self.cancel_button = QtWidgets.QPushButton("Cancel")

        # --- Layouts ---
        main_layout = QtWidgets.QVBoxLayout(self)
        form_layout = QtWidgets.QFormLayout()
        inference_layout = QtWidgets.QHBoxLayout()
        button_layout = QtWidgets.QHBoxLayout()

        # --- Setup Form Layout (API Keys) ---
        form_layout.addRow("OPENAI_API_KEY:", self.openai_api_key_input)
        form_layout.addRow("GOOGLE_AI_STUDIO_API_KEY:", self.google_api_key_input)
        main_layout.addLayout(form_layout)

        # --- Setup Inference Layout (Radio Buttons) ---
        inference_layout.addWidget(self.inference_label)
        inference_layout.addStretch() # Add space before buttons

        for idx, model in enumerate(AIModel):
            radio_button = QtWidgets.QRadioButton(model.name.upper())
            self.inference_radio_buttons[model] = radio_button
            self.inference_button_group.addButton(radio_button, idx) # Associate enum value
            inference_layout.addWidget(radio_button)

        main_layout.addLayout(inference_layout)
        main_layout.addStretch(1) # Add stretchable space before buttons

        # --- Setup Button Layout ---
        button_layout.addStretch(1) # Push buttons to the right
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        # --- Connections ---
        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject) # Close dialog without saving

        # --- Load Initial Settings ---
        self._load_settings()

    def _load_settings(self):
        """Loads the current settings into the dialog's widgets."""
        self.openai_api_key_input.setText(self.current_settings.get("OPENAI_API_KEY", ""))
        self.google_api_key_input.setText(self.current_settings.get("GOOGLE_AI_STUDIO_API_KEY", ""))

        selected_model_name = self.current_settings.get("Selected Inference Provider", AIModel.OPENAI.name) # Default to OPENAI
        try:
            selected_model = AIModel[selected_model_name]
            if selected_model in self.inference_radio_buttons:
                self.inference_radio_buttons[selected_model].setChecked(True)
            else:
                # Handle case where saved model isn't in current enum (e.g., outdated settings)
                # Default to the first available radio button
                 if self.inference_radio_buttons:
                     first_button = next(iter(self.inference_radio_buttons.values()))
                     first_button.setChecked(True)
        except KeyError:
             # Handle case where saved model name is invalid
             if self.inference_radio_buttons:
                 first_button = next(iter(self.inference_radio_buttons.values()))
                 first_button.setChecked(True)


    def save_settings(self):
        """Gathers the settings from the widgets and emits the settings_saved signal."""
        new_settings = {}
        new_settings["OPENAI_API_KEY"] = self.openai_api_key_input.text()
        new_settings["GOOGLE_AI_STUDIO_API_KEY"] = self.google_api_key_input.text()

        selected_button = self.inference_button_group.checkedButton()
        if selected_button:
            # Find the AIModel enum member corresponding to the selected button
            for model, button in self.inference_radio_buttons.items():
                if button == selected_button:
                    new_settings["Selected Inference Provider"] = model.name
                    break
        else:
            # Handle case where no button is selected (shouldn't happen with defaults)
            # Optionally default to the first model or log an error
            if self.inference_radio_buttons:
                first_model = next(iter(self.inference_radio_buttons.keys()))
                new_settings["Selected Inference Provider"] = first_model.name


        # In a real application, you would save these settings to a file (.sagesettings) here
        # For this example, we just emit a signal and accept the dialog
        print(f"Settings Dialog: Saving {new_settings}") # Placeholder
        self.settings_saved.emit(new_settings)
        self.accept() # Close the dialog successfully


class AppMenuBar(QtWidgets.QMenuBar):
    new_project_requested = Signal()
    open_project_requested = Signal()
    save_project_requested = Signal()
    # Optional: Add close project signal
    # close_project_requested = Signal()
    settings_updated = Signal(dict) # Signal to notify main window about settings changes

    undo_action = Signal()
    redo_action = Signal()

    def __init__(self, parent_window): # Removed palettes and active_palette_name
        super().__init__(parent_window)
        self.parent_window = parent_window
        # Removed theme-related attributes
        self.save_action = None # Initialize
        self.close_action = None # Initialize

        self._create_file_menu()
        self._create_edit_menu()
        self._create_settings_menu()
        # Removed _create_view_menu call
        self._create_help_menu()

        # --- Member variable to hold current settings (replace with actual loading) ---
        self.current_app_settings = self._load_initial_settings()


    def _load_initial_settings(self):
        """
        Placeholder for loading settings from .sagesettings.
        Returns a dictionary of settings.
        """
        # In a real app, load from file here
        with open(SETTINGS_FILE_NAME) as f:
            data = json.load(f)
        return data

    def _create_file_menu(self):
        file_menu = self.addMenu("&File")

        new_action = QtGui.QAction("&New Project...", self.parent_window)
        new_action.setShortcut(QtGui.QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_project_requested)
        file_menu.addAction(new_action)

        open_action = QtGui.QAction("&Open Project...", self.parent_window)
        open_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_project_requested)
        file_menu.addAction(open_action)

        self.save_action = QtGui.QAction("&Save Project", self.parent_window)
        self.save_action.setShortcut(QtGui.QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project_requested)
        self.save_action.setEnabled(False) # Disabled until project loaded
        file_menu.addAction(self.save_action)

        # Optional: Add Close Project Action
        # self.close_action = QtGui.QAction("&Close Project", self.parent_window)
        # self.close_action.triggered.connect(self.close_project_requested) # Connect to new signal
        # self.close_action.setEnabled(False) # Disabled until project loaded
        # file_menu.addAction(self.close_action)

        file_menu.addSeparator()
        exit_action = QtGui.QAction("E&xit", self.parent_window)
        exit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.parent_window.close)
        file_menu.addAction(exit_action)

    def _create_edit_menu(self):
        edit_menu = self.addMenu("&Edit")
        undo_action = QtGui.QAction("&Undo", self.parent_window); undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo); undo_action.triggered.connect(self.undo_action); edit_menu.addAction(undo_action)
        redo_action = QtGui.QAction("&Redo", self.parent_window); redo_action.setShortcut(QtGui.QKeySequence.StandardKey.Redo); redo_action.triggered.connect(self.redo_action); edit_menu.addAction(redo_action)

    def _create_settings_menu(self):
        settings_menu = self.addMenu("&Settings")
        prefs_action = QtGui.QAction("&LLM Settings", self.parent_window)
        # Connect to the method that opens the settings dialog
        prefs_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(prefs_action)

    def _create_help_menu(self):
        help_menu = self.addMenu("&Help")
        about_action = QtGui.QAction("&About...", self.parent_window); about_action.triggered.connect(self.placeholder_action); help_menu.addAction(about_action)

    def set_project_actions_enabled(self, enabled: bool):
        """ Enables/disables Save and Close actions based on project state. """
        if self.save_action:
            self.save_action.setEnabled(enabled)
        # if self.close_action: # Enable/disable close action if added
            # self.close_action.setEnabled(enabled)

    def placeholder_action(self):
        sender = self.parent_window.sender()
        action_text = sender.text().replace("&", "") if sender else "Unknown Action"
        # Access console via parent window safely
        if hasattr(self.parent_window, 'console_widget') and hasattr(self.parent_window.console_widget, 'log_message'):
            self.parent_window.console_widget.log_message(f"Action '{action_text}' triggered (placeholder).")
        else:
            print(f"Action '{action_text}' triggered (placeholder) - Console not found.")

    def _open_settings_dialog(self):
        """Creates and shows the SettingsDialog."""
        # Pass the current settings to the dialog
        dialog = SettingsDialog(self.current_app_settings, self.parent_window)
        # Connect the dialog's save signal to update our internal settings
        dialog.settings_saved.connect(self._handle_settings_saved)
        dialog.exec() # Show the dialog modally

    def _handle_settings_saved(self, new_settings: dict):
        """
        Slot to receive saved settings from the dialog, update internal state,
        and emit a signal for the main application.
        """
        print("MenuBar: Received saved settings:", new_settings)
        self.current_app_settings = new_settings
        # Emit signal so the main application can react (e.g., update inference backend)
        self.settings_updated.emit(new_settings)
        # In a real application, you might trigger the actual saving to .sagesettings here
        # or the main window might do it upon receiving the settings_updated signal.
        with open(SETTINGS_FILE_NAME, "w") as f:
            json.dump(new_settings, f)
        print("MenuBar: Settings updated internally.")
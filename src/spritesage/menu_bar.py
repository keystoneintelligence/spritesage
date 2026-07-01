"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import json
from PySide6 import QtWidgets, QtGui
from PySide6.QtCore import Signal

from .inference import AIModel
from .config import SETTINGS_FILE_NAME, TESTING_PROVIDER_ENABLED
from .recent_projects import RecentProject, recent_project_label
from .ai_models import (
    CAPABILITY_IMAGE,
    CAPABILITY_TEXT,
    GOOGLE_IMAGE_MODEL_SETTING,
    GOOGLE_TEXT_MODEL_SETTING,
    OPENAI_IMAGE_MODEL_SETTING,
    OPENAI_TEXT_MODEL_SETTING,
    PROVIDER_GOOGLEAI,
    PROVIDER_OPENAI,
    get_cached_model_options,
    model_options_for_capability,
    refresh_model_cache,
)


class SettingsDialog(QtWidgets.QDialog):
    """
    A dialog window for configuring application settings like API keys and inference model.
    """

    # Signal emitted when settings are saved, passing the new settings dictionary
    settings_saved = Signal(dict)

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(450)  # Adjust as needed

        self.current_settings = current_settings

        # --- Widgets ---
        self.openai_api_key_input = QtWidgets.QLineEdit()
        self.openai_api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)

        self.google_api_key_input = QtWidgets.QLineEdit()
        self.google_api_key_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)

        self.openai_text_model_input = self._create_model_combo()
        self.openai_image_model_input = self._create_model_combo()
        self.google_text_model_input = self._create_model_combo()
        self.google_image_model_input = self._create_model_combo()
        self.model_inputs = {
            OPENAI_TEXT_MODEL_SETTING: self.openai_text_model_input,
            OPENAI_IMAGE_MODEL_SETTING: self.openai_image_model_input,
            GOOGLE_TEXT_MODEL_SETTING: self.google_text_model_input,
            GOOGLE_IMAGE_MODEL_SETTING: self.google_image_model_input,
        }

        self.openai_refresh_button = QtWidgets.QPushButton("Refresh OpenAI")
        self.google_refresh_button = QtWidgets.QPushButton("Refresh Google")

        self.inference_label = QtWidgets.QLabel("Selected Inference")
        self.inference_button_group = QtWidgets.QButtonGroup(self)
        self.inference_radio_buttons = {}  # Store radio buttons for easy access

        self.save_button = QtWidgets.QPushButton("Save")
        self.cancel_button = QtWidgets.QPushButton("Cancel")

        # --- Layouts ---
        main_layout = QtWidgets.QVBoxLayout(self)
        form_layout = QtWidgets.QFormLayout()
        inference_layout = QtWidgets.QHBoxLayout()
        button_layout = QtWidgets.QHBoxLayout()

        # --- Setup Form Layout (API Keys) ---
        form_layout.addRow(
            "OPENAI_API_KEY:",
            self._with_button(self.openai_api_key_input, self.openai_refresh_button),
        )
        form_layout.addRow(
            "GOOGLE_AI_STUDIO_API_KEY:",
            self._with_button(self.google_api_key_input, self.google_refresh_button),
        )
        form_layout.addRow("OpenAI text model:", self.openai_text_model_input)
        form_layout.addRow("OpenAI image model:", self.openai_image_model_input)
        form_layout.addRow("Google text model:", self.google_text_model_input)
        form_layout.addRow("Google image model:", self.google_image_model_input)
        main_layout.addLayout(form_layout)

        # --- Setup Inference Layout (Radio Buttons) ---
        inference_layout.addWidget(self.inference_label)
        inference_layout.addStretch()  # Add space before buttons

        for idx, model in enumerate(self._available_models()):
            radio_button = QtWidgets.QRadioButton(model.name.upper())
            self.inference_radio_buttons[model] = radio_button
            self.inference_button_group.addButton(radio_button, idx)  # Associate enum value
            inference_layout.addWidget(radio_button)

        main_layout.addLayout(inference_layout)
        main_layout.addStretch(1)  # Add stretchable space before buttons

        # --- Setup Button Layout ---
        button_layout.addStretch(1)  # Push buttons to the right
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        # --- Connections ---
        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject)  # Close dialog without saving
        self.openai_refresh_button.clicked.connect(
            lambda: self.refresh_provider_models(PROVIDER_OPENAI)
        )
        self.google_refresh_button.clicked.connect(
            lambda: self.refresh_provider_models(PROVIDER_GOOGLEAI)
        )

        # --- Load Initial Settings ---
        self._load_settings()

    @staticmethod
    def _with_button(field: QtWidgets.QWidget, button: QtWidgets.QWidget) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)
        layout.addWidget(button)
        return row

    @staticmethod
    def _available_models():
        return [model for model in AIModel if model != AIModel.TESTING or TESTING_PROVIDER_ENABLED]

    @staticmethod
    def _create_model_combo() -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        return combo

    @staticmethod
    def _model_label(option) -> str:
        prefix = "Recommended: " if option.recommended else ""
        suffix = f" - {option.description}" if option.description else ""
        return f"{prefix}{option.display_name} ({option.model_id}){suffix}"

    def _populate_combo(self, combo: QtWidgets.QComboBox, options, selected_model: str = ""):
        combo.blockSignals(True)
        combo.clear()
        for option in options:
            combo.addItem(self._model_label(option), option.model_id)
        if selected_model and self._select_model_id(combo, selected_model):
            pass
        elif combo.count():
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _clear_provider_models(self, provider: str):
        for combo in self._provider_combos(provider):
            combo.clear()
            combo.setEnabled(False)
        self._set_provider_available(provider, False)

    def _provider_combos(self, provider: str):
        if provider == PROVIDER_OPENAI:
            return [self.openai_text_model_input, self.openai_image_model_input]
        return [self.google_text_model_input, self.google_image_model_input]

    def _provider_model(self, provider: str):
        if provider == PROVIDER_OPENAI:
            return AIModel.OPENAI
        if provider == PROVIDER_GOOGLEAI:
            return AIModel.GOOGLEAI
        return AIModel.TESTING

    def _set_provider_available(self, provider: str, available: bool):
        model = self._provider_model(provider)
        if model in self.inference_radio_buttons:
            self.inference_radio_buttons[model].setEnabled(available)

    def _first_enabled_model(self):
        for model in AIModel:
            button = self.inference_radio_buttons.get(model)
            if button and button.isEnabled():
                return model
        return None

    def _populate_provider_models(self, provider: str, options=None):
        options = get_cached_model_options(provider) if options is None else options
        text_options = model_options_for_capability(provider, CAPABILITY_TEXT, options)
        image_options = model_options_for_capability(provider, CAPABILITY_IMAGE, options)
        if provider == PROVIDER_OPENAI:
            text_combo = self.openai_text_model_input
            image_combo = self.openai_image_model_input
            text_setting = OPENAI_TEXT_MODEL_SETTING
            image_setting = OPENAI_IMAGE_MODEL_SETTING
        else:
            text_combo = self.google_text_model_input
            image_combo = self.google_image_model_input
            text_setting = GOOGLE_TEXT_MODEL_SETTING
            image_setting = GOOGLE_IMAGE_MODEL_SETTING

        if not text_options or not image_options:
            self._clear_provider_models(provider)
            return False

        self._populate_combo(text_combo, text_options, self.current_settings.get(text_setting, ""))
        self._populate_combo(
            image_combo, image_options, self.current_settings.get(image_setting, "")
        )
        text_combo.setEnabled(True)
        image_combo.setEnabled(True)
        self._set_provider_available(provider, True)
        return True

    @staticmethod
    def _select_model_id(combo: QtWidgets.QComboBox, model_id: str) -> bool:
        for index in range(combo.count()):
            if combo.itemData(index) == model_id:
                combo.setCurrentIndex(index)
                return True
        return False

    @staticmethod
    def _selected_model_id(combo: QtWidgets.QComboBox) -> str:
        if not combo.isEnabled():
            return ""
        index = combo.currentIndex()
        if index >= 0 and combo.currentText() == combo.itemText(index):
            data = combo.itemData(index)
            if data:
                return str(data)
        return combo.currentText().strip()

    def refresh_provider_models(self, provider: str):
        if provider == PROVIDER_OPENAI:
            provider_name = "OpenAI"
            api_key = self.openai_api_key_input.text().strip()
        else:
            provider_name = "Google"
            api_key = self.google_api_key_input.text().strip()

        if not api_key:
            article = "an" if provider_name[0].lower() in "aeiou" else "a"
            QtWidgets.QMessageBox.warning(
                self,
                f"{provider_name} Models",
                f"Enter {article} {provider_name} API key before refreshing models.",
            )
            return

        try:
            options = refresh_model_cache(provider, api_key)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                f"{provider_name} Models",
                f"Could not refresh {provider_name} models.\n\n{e}",
            )
            self._clear_provider_models(provider)
            return

        if not self._populate_provider_models(provider, options):
            QtWidgets.QMessageBox.warning(
                self,
                f"{provider_name} Models",
                f"No compatible {provider_name} text and image models were returned for this API key.",
            )

    def _load_settings(self):
        """Loads the current settings into the dialog's widgets."""
        self.openai_api_key_input.setText(self.current_settings.get("OPENAI_API_KEY", ""))
        self.google_api_key_input.setText(self.current_settings.get("GOOGLE_AI_STUDIO_API_KEY", ""))
        if AIModel.OPENAI in self.inference_radio_buttons:
            self.inference_radio_buttons[AIModel.OPENAI].setEnabled(False)
        if AIModel.GOOGLEAI in self.inference_radio_buttons:
            self.inference_radio_buttons[AIModel.GOOGLEAI].setEnabled(False)
        if AIModel.TESTING in self.inference_radio_buttons:
            self.inference_radio_buttons[AIModel.TESTING].setEnabled(True)
        self._populate_provider_models(PROVIDER_OPENAI)
        self._populate_provider_models(PROVIDER_GOOGLEAI)

        selected_model_name = self.current_settings.get(
            "Selected Inference Provider", AIModel.TESTING.name
        )
        try:
            selected_model = AIModel[selected_model_name]
            if (
                selected_model in self.inference_radio_buttons
                and self.inference_radio_buttons[selected_model].isEnabled()
            ):
                self.inference_radio_buttons[selected_model].setChecked(True)
            else:
                # Handle case where saved model isn't in current enum (e.g., outdated settings)
                # Default to the first enabled radio button
                fallback_model = self._first_enabled_model()
                if fallback_model is not None:
                    self.inference_radio_buttons[fallback_model].setChecked(True)
        except KeyError:
            # Handle case where saved model name is invalid
            fallback_model = self._first_enabled_model()
            if fallback_model is not None:
                self.inference_radio_buttons[fallback_model].setChecked(True)

    def save_settings(self):
        """Gathers the settings from the widgets and emits the settings_saved signal."""
        new_settings = {}
        new_settings["OPENAI_API_KEY"] = self.openai_api_key_input.text()
        new_settings["GOOGLE_AI_STUDIO_API_KEY"] = self.google_api_key_input.text()
        for key, combo in self.model_inputs.items():
            selected = self._selected_model_id(combo)
            if selected:
                new_settings[key] = selected
            elif self.current_settings.get(key):
                new_settings[key] = self.current_settings[key]

        selected_button = self.inference_button_group.checkedButton()
        if selected_button and selected_button.isEnabled():
            # Find the AIModel enum member corresponding to the selected button
            for model, button in self.inference_radio_buttons.items():
                if button == selected_button:
                    new_settings["Selected Inference Provider"] = model.name
                    break
        else:
            # Handle case where no button is selected (shouldn't happen with defaults)
            # Optionally default to the first model or log an error
            fallback_model = self._first_enabled_model()
            if fallback_model is not None:
                new_settings["Selected Inference Provider"] = fallback_model.name
            elif self.current_settings.get("Selected Inference Provider"):
                new_settings["Selected Inference Provider"] = self.current_settings[
                    "Selected Inference Provider"
                ]

        # In a real application, you would save these settings to a file (.sagesettings) here
        # For this example, we just emit a signal and accept the dialog
        print(f"Settings Dialog: Saving {new_settings}")  # Placeholder
        self.settings_saved.emit(new_settings)
        self.accept()  # Close the dialog successfully


class AppMenuBar(QtWidgets.QMenuBar):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_recent_project_requested = Signal(str)
    save_project_requested = Signal()
    export_project_requested = Signal()
    export_sprite_requested = Signal()
    # Optional: Add close project signal
    # close_project_requested = Signal()
    settings_updated = Signal(dict)  # Signal to notify main window about settings changes

    undo_action = Signal()
    redo_action = Signal()

    def __init__(
        self,
        parent_window,
        settings_file_path: str | None = None,
        initial_settings: dict | None = None,
    ):  # Removed palettes and active_palette_name
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.settings_file_path = settings_file_path or getattr(
            parent_window, "settings_file_path", SETTINGS_FILE_NAME
        )
        # Removed theme-related attributes
        self.file_menu = None
        self.save_action = None  # Initialize
        self.open_recent_menu = None
        self.export_project_action = None
        self.export_sprite_action = None
        self.close_action = None  # Initialize
        self.undo_menu_action = None
        self.redo_menu_action = None

        self._create_file_menu()
        self._create_edit_menu()
        self._create_settings_menu()
        # Removed _create_view_menu call
        self._create_help_menu()

        # --- Member variable to hold current settings (replace with actual loading) ---
        self.current_app_settings = (
            initial_settings.copy()
            if initial_settings is not None
            else self._load_initial_settings()
        )

    def _load_initial_settings(self):
        """
        Placeholder for loading settings from .sagesettings.
        Returns a dictionary of settings.
        """
        # In a real app, load from file here
        with open(self.settings_file_path) as f:
            data = json.load(f)
        return data

    def _create_file_menu(self):
        file_menu = self.addMenu("&File")
        self.file_menu = file_menu

        new_action = QtGui.QAction("&New Project...", self.parent_window)
        new_action.setShortcut(QtGui.QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_project_requested)
        file_menu.addAction(new_action)

        open_action = QtGui.QAction("&Open Project...", self.parent_window)
        open_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_project_requested)
        file_menu.addAction(open_action)

        self.open_recent_menu = file_menu.addMenu("Open &Recent")
        self.update_recent_projects([])

        self.save_action = QtGui.QAction("&Save Project", self.parent_window)
        self.save_action.setShortcut(QtGui.QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project_requested)
        self.save_action.setEnabled(False)  # Disabled until project loaded
        file_menu.addAction(self.save_action)

        export_menu = file_menu.addMenu("&Export")
        self.export_project_action = QtGui.QAction("&Project...", self.parent_window)
        self.export_project_action.triggered.connect(self.export_project_requested)
        self.export_project_action.setEnabled(False)
        export_menu.addAction(self.export_project_action)

        self.export_sprite_action = QtGui.QAction("&Sprite...", self.parent_window)
        self.export_sprite_action.triggered.connect(self.export_sprite_requested)
        self.export_sprite_action.setEnabled(False)
        export_menu.addAction(self.export_sprite_action)

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

    def update_recent_projects(self, recent_projects: list[RecentProject]):
        if self.open_recent_menu is None:
            return

        self.open_recent_menu.clear()
        if not recent_projects:
            empty_action = QtGui.QAction("No Recent Projects", self.parent_window)
            empty_action.setEnabled(False)
            self.open_recent_menu.addAction(empty_action)
            self.open_recent_menu.setEnabled(False)
            return

        self.open_recent_menu.setEnabled(True)
        for project in recent_projects:
            action = QtGui.QAction(recent_project_label(project), self.parent_window)
            action.setToolTip(project["path"])
            action.triggered.connect(
                lambda checked=False, path=project["path"]: self.open_recent_project_requested.emit(
                    path
                )
            )
            self.open_recent_menu.addAction(action)

    def _create_edit_menu(self):
        edit_menu = self.addMenu("&Edit")
        self.undo_menu_action = QtGui.QAction("&Undo", self.parent_window)
        self.undo_menu_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.undo_menu_action.triggered.connect(self.undo_action)
        self.undo_menu_action.setEnabled(False)
        edit_menu.addAction(self.undo_menu_action)

        self.redo_menu_action = QtGui.QAction("&Redo", self.parent_window)
        self.redo_menu_action.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        self.redo_menu_action.triggered.connect(self.redo_action)
        self.redo_menu_action.setEnabled(False)
        edit_menu.addAction(self.redo_menu_action)

    def set_undo_redo_state(self, state):
        if self.undo_menu_action is None or self.redo_menu_action is None:
            return

        can_undo = bool(getattr(state, "can_undo", False))
        can_redo = bool(getattr(state, "can_redo", False))
        undo_text = str(getattr(state, "undo_text", "") or "")
        redo_text = str(getattr(state, "redo_text", "") or "")

        self.undo_menu_action.setEnabled(can_undo)
        self.undo_menu_action.setText(f"&Undo {undo_text}" if undo_text else "&Undo")
        self.redo_menu_action.setEnabled(can_redo)
        self.redo_menu_action.setText(f"&Redo {redo_text}" if redo_text else "&Redo")

    def _create_settings_menu(self):
        settings_menu = self.addMenu("&Settings")
        prefs_action = QtGui.QAction("&LLM Settings", self.parent_window)
        # Connect to the method that opens the settings dialog
        prefs_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(prefs_action)

    def _create_help_menu(self):
        help_menu = self.addMenu("&Help")
        about_action = QtGui.QAction("&About...", self.parent_window)
        about_action.triggered.connect(self.placeholder_action)
        help_menu.addAction(about_action)

    def set_project_actions_enabled(self, enabled: bool):
        """Enables/disables Save and Close actions based on project state."""
        if self.save_action:
            self.save_action.setEnabled(enabled)
        if self.export_project_action:
            self.export_project_action.setEnabled(enabled)
        if self.export_sprite_action:
            self.export_sprite_action.setEnabled(enabled)
        # if self.close_action: # Enable/disable close action if added
        # self.close_action.setEnabled(enabled)

    def placeholder_action(self):
        sender = self.parent_window.sender()
        action_text = sender.text().replace("&", "") if sender else "Unknown Action"
        # Access console via parent window safely
        if hasattr(self.parent_window, "console_widget") and hasattr(
            self.parent_window.console_widget, "log_message"
        ):
            self.parent_window.console_widget.log_message(
                f"Action '{action_text}' triggered (placeholder)."
            )
        else:
            print(f"Action '{action_text}' triggered (placeholder) - Console not found.")

    def _open_settings_dialog(self):
        """Creates and shows the SettingsDialog."""
        # Pass the current settings to the dialog
        dialog = SettingsDialog(self.current_app_settings, self.parent_window)
        # Connect the dialog's save signal to update our internal settings
        dialog.settings_saved.connect(self._handle_settings_saved)
        dialog.exec()  # Show the dialog modally

    def _handle_settings_saved(self, new_settings: dict):
        """
        Slot to receive saved settings from the dialog, update internal state,
        and emit a signal for the main application.
        """
        print("MenuBar: Received saved settings:", new_settings)
        self.current_app_settings = {**self.current_app_settings, **new_settings}
        # Emit signal so the main application can react (e.g., update inference backend)
        self.settings_updated.emit(self.current_app_settings)
        # In a real application, you might trigger the actual saving to .sagesettings here
        # or the main window might do it upon receiving the settings_updated signal.
        if hasattr(self.parent_window, "settings"):
            self.parent_window.settings = self.current_app_settings
        with open(self.settings_file_path, "w") as f:
            json.dump(self.current_app_settings, f)
        print("MenuBar: Settings updated internally.")

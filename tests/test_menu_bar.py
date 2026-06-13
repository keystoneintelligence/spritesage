import importlib
import json
import pytest
from PySide6 import QtWidgets, QtGui

from spritesage import menu_bar
from spritesage.menu_bar import SettingsDialog, AppMenuBar
from spritesage.inference import AIModel
from spritesage import ai_models
from spritesage.ai_models import CAPABILITY_IMAGE, CAPABILITY_TEXT, ModelOption, PROVIDER_GOOGLEAI, PROVIDER_OPENAI

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

def test_import_menu_bar():
    module = importlib.import_module('spritesage.menu_bar')
    assert module is not None

@pytest.fixture(autouse=True)
def clear_model_cache():
    ai_models.set_cached_model_options(PROVIDER_OPENAI, [])
    ai_models.set_cached_model_options(PROVIDER_GOOGLEAI, [])
    yield
    ai_models.set_cached_model_options(PROVIDER_OPENAI, [])
    ai_models.set_cached_model_options(PROVIDER_GOOGLEAI, [])

class TestSettingsDialog:

    def test_load_default_settings(self, qapp):
        dialog = SettingsDialog({}, parent=None)
        assert dialog.openai_api_key_input.text() == ""
        assert dialog.google_api_key_input.text() == ""
        assert not dialog.openai_text_model_input.isEnabled()
        assert not dialog.openai_image_model_input.isEnabled()
        assert not dialog.google_text_model_input.isEnabled()
        assert not dialog.google_image_model_input.isEnabled()
        assert not dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()
        assert not dialog.inference_radio_buttons[AIModel.GOOGLEAI].isEnabled()
        assert dialog.inference_radio_buttons[AIModel.TESTING].isEnabled()
        # Only TESTING selected by default when provider models are unavailable
        for model, btn in dialog.inference_radio_buttons.items():
            if model == AIModel.TESTING:
                assert btn.isChecked()
            else:
                assert not btn.isChecked()

    def test_load_selected_model_from_cached_discovery(self, qapp):
        ai_models.set_cached_model_options(PROVIDER_OPENAI, [
            ModelOption(PROVIDER_OPENAI, "openai-text", "OpenAI Text", (CAPABILITY_TEXT,), source="api"),
            ModelOption(PROVIDER_OPENAI, "openai-image", "OpenAI Image", (CAPABILITY_IMAGE,), source="api"),
        ])
        ai_models.set_cached_model_options(PROVIDER_GOOGLEAI, [
            ModelOption(PROVIDER_GOOGLEAI, "google-text", "Google Text", (CAPABILITY_TEXT,), source="api"),
            ModelOption(PROVIDER_GOOGLEAI, "google-image", "Google Image", (CAPABILITY_IMAGE,), source="api"),
        ])
        settings = {
            "OPENAI_API_KEY": "key1",
            "GOOGLE_AI_STUDIO_API_KEY": "key2",
            "Selected Inference Provider": AIModel.GOOGLEAI.name,
            "OPENAI_TEXT_MODEL": "openai-text",
            "OPENAI_IMAGE_MODEL": "openai-image",
            "GOOGLE_TEXT_MODEL": "google-text",
            "GOOGLE_IMAGE_MODEL": "google-image",
        }
        dialog = SettingsDialog(settings, parent=None)
        assert dialog.openai_api_key_input.text() == "key1"
        assert dialog.google_api_key_input.text() == "key2"
        assert dialog.openai_text_model_input.isEnabled()
        assert dialog.openai_image_model_input.isEnabled()
        assert dialog.google_text_model_input.isEnabled()
        assert dialog.google_image_model_input.isEnabled()
        assert dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()
        assert dialog.inference_radio_buttons[AIModel.GOOGLEAI].isEnabled()
        assert dialog._selected_model_id(dialog.openai_text_model_input) == "openai-text"
        assert dialog._selected_model_id(dialog.openai_image_model_input) == "openai-image"
        assert dialog._selected_model_id(dialog.google_text_model_input) == "google-text"
        assert dialog._selected_model_id(dialog.google_image_model_input) == "google-image"
        for model, btn in dialog.inference_radio_buttons.items():
            if model == AIModel.GOOGLEAI:
                assert btn.isChecked()
            else:
                assert not btn.isChecked()

    def test_load_invalid_model(self, qapp):
        settings = {
            "Selected Inference Provider": "INVALID_MODEL"
        }
        dialog = SettingsDialog(settings, parent=None)
        # Fallback to first enabled radio button
        for model, btn in dialog.inference_radio_buttons.items():
            if model == AIModel.TESTING:
                assert btn.isChecked()
            else:
                assert not btn.isChecked()

    def test_unavailable_saved_provider_is_not_selectable(self, qapp):
        ai_models.set_cached_model_options(PROVIDER_OPENAI, [
            ModelOption(PROVIDER_OPENAI, "openai-text", "OpenAI Text", (CAPABILITY_TEXT,), source="api"),
            ModelOption(PROVIDER_OPENAI, "openai-image", "OpenAI Image", (CAPABILITY_IMAGE,), source="api"),
        ])
        dialog = SettingsDialog({"Selected Inference Provider": AIModel.GOOGLEAI.name}, parent=None)

        assert dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()
        assert not dialog.inference_radio_buttons[AIModel.GOOGLEAI].isEnabled()
        assert dialog.inference_radio_buttons[AIModel.OPENAI].isChecked()

    def test_testing_provider_hidden_when_disabled(self, qapp, monkeypatch):
        monkeypatch.setattr(menu_bar, "TESTING_PROVIDER_ENABLED", False)
        dialog = SettingsDialog({}, parent=None)

        assert AIModel.TESTING not in dialog.inference_radio_buttons
        assert AIModel.OPENAI in dialog.inference_radio_buttons
        assert AIModel.GOOGLEAI in dialog.inference_radio_buttons
        assert dialog.inference_button_group.checkedButton() is None

    def test_save_settings_emits_signal(self, qapp):
        ai_models.set_cached_model_options(PROVIDER_OPENAI, [
            ModelOption(PROVIDER_OPENAI, "o-text", "OpenAI Text", (CAPABILITY_TEXT,), source="api"),
            ModelOption(PROVIDER_OPENAI, "o-image", "OpenAI Image", (CAPABILITY_IMAGE,), source="api"),
        ])
        ai_models.set_cached_model_options(PROVIDER_GOOGLEAI, [
            ModelOption(PROVIDER_GOOGLEAI, "g-text", "Google Text", (CAPABILITY_TEXT,), source="api"),
            ModelOption(PROVIDER_GOOGLEAI, "g-image", "Google Image", (CAPABILITY_IMAGE,), source="api"),
        ])
        dialog = SettingsDialog({}, parent=None)
        dialog.openai_api_key_input.setText("abc")
        dialog.google_api_key_input.setText("def")
        # Select TESTING model
        dialog.inference_radio_buttons[AIModel.TESTING].setChecked(True)
        captured = []
        dialog.settings_saved.connect(lambda s: captured.append(s))
        dialog.save_settings()
        assert len(captured) == 1
        saved = captured[0]
        assert saved["OPENAI_API_KEY"] == "abc"
        assert saved["GOOGLE_AI_STUDIO_API_KEY"] == "def"
        assert saved["OPENAI_TEXT_MODEL"] == "o-text"
        assert saved["OPENAI_IMAGE_MODEL"] == "o-image"
        assert saved["GOOGLE_TEXT_MODEL"] == "g-text"
        assert saved["GOOGLE_IMAGE_MODEL"] == "g-image"
        assert saved["Selected Inference Provider"] == AIModel.TESTING.name

    def test_save_preserves_existing_models_when_dropdowns_disabled(self, qapp):
        dialog = SettingsDialog({
            "OPENAI_TEXT_MODEL": "saved-openai-text",
            "OPENAI_IMAGE_MODEL": "saved-openai-image",
        }, parent=None)
        captured = []
        dialog.settings_saved.connect(lambda s: captured.append(s))
        dialog.save_settings()

        assert captured[0]["OPENAI_TEXT_MODEL"] == "saved-openai-text"
        assert captured[0]["OPENAI_IMAGE_MODEL"] == "saved-openai-image"

    def test_refresh_openai_models_enables_openai_dropdowns(self, qapp, monkeypatch):
        dialog = SettingsDialog({}, parent=None)
        dialog.openai_api_key_input.setText("openai-key")

        def fake_refresh(provider, api_key):
            assert provider == PROVIDER_OPENAI
            assert api_key == "openai-key"
            return [
                ModelOption(PROVIDER_OPENAI, "gpt-6-mini", "GPT-6 mini", (CAPABILITY_TEXT,), source="api"),
                ModelOption(PROVIDER_OPENAI, "gpt-image-3", "GPT Image 3", (CAPABILITY_IMAGE,), source="api"),
            ]

        monkeypatch.setattr(menu_bar, "refresh_model_cache", fake_refresh)
        dialog.refresh_provider_models(PROVIDER_OPENAI)

        openai_text_models = [dialog.openai_text_model_input.itemData(i) for i in range(dialog.openai_text_model_input.count())]
        openai_image_models = [dialog.openai_image_model_input.itemData(i) for i in range(dialog.openai_image_model_input.count())]

        assert "gpt-6-mini" in openai_text_models
        assert "gpt-image-3" in openai_image_models
        assert dialog.openai_text_model_input.isEnabled()
        assert dialog.openai_image_model_input.isEnabled()
        assert dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()
        assert not dialog.inference_radio_buttons[AIModel.GOOGLEAI].isEnabled()
        assert dialog.inference_radio_buttons[AIModel.TESTING].isEnabled()
        assert not dialog.google_text_model_input.isEnabled()
        assert not dialog.google_image_model_input.isEnabled()

    def test_refresh_provider_models_reports_missing_key(self, qapp, monkeypatch):
        dialog = SettingsDialog({}, parent=None)
        warnings = []
        monkeypatch.setattr(
            menu_bar.QtWidgets.QMessageBox,
            "warning",
            lambda parent, title, body: warnings.append((title, body)),
        )

        dialog.refresh_provider_models(PROVIDER_OPENAI)

        assert warnings == [("OpenAI Models", "Enter an OpenAI API key before refreshing models.")]

    def test_refresh_provider_models_reports_errors(self, qapp, monkeypatch):
        dialog = SettingsDialog({}, parent=None)
        dialog.openai_api_key_input.setText("openai-key")
        warnings = []

        def fake_refresh(provider, api_key):
            raise RuntimeError("api unavailable")

        monkeypatch.setattr(menu_bar, "refresh_model_cache", fake_refresh)
        monkeypatch.setattr(
            menu_bar.QtWidgets.QMessageBox,
            "warning",
            lambda parent, title, body: warnings.append((title, body)),
        )

        dialog.refresh_provider_models(PROVIDER_OPENAI)

        assert warnings and "api unavailable" in warnings[0][1]
        assert not dialog.openai_text_model_input.isEnabled()
        assert not dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()

    def test_refresh_provider_models_reports_no_compatible_models(self, qapp, monkeypatch):
        dialog = SettingsDialog({}, parent=None)
        dialog.openai_api_key_input.setText("openai-key")
        warnings = []
        monkeypatch.setattr(menu_bar, "refresh_model_cache", lambda provider, api_key: [])
        monkeypatch.setattr(
            menu_bar.QtWidgets.QMessageBox,
            "warning",
            lambda parent, title, body: warnings.append((title, body)),
        )

        dialog.refresh_provider_models(PROVIDER_OPENAI)

        assert warnings and "No compatible OpenAI text and image models" in warnings[0][1]
        assert not dialog.inference_radio_buttons[AIModel.OPENAI].isEnabled()

class TestAppMenuBar:

    def test_file_menu_actions_emit_signals(self, tmp_path, monkeypatch, qapp):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(menu_bar, 'SETTINGS_FILE_NAME', str(settings_file))
        settings_file.write_text(json.dumps({}))
        parent = QtWidgets.QWidget()
        captured = {"new": False, "open": False, "save": False, "exit": False}
        parent.close = lambda: captured.__setitem__("exit", True)
        bar = AppMenuBar(parent)
        bar.new_project_requested.connect(lambda: captured.__setitem__("new", True))
        bar.open_project_requested.connect(lambda: captured.__setitem__("open", True))
        bar.save_project_requested.connect(lambda: captured.__setitem__("save", True))
        # Locate File menu and actions
        file_menu_action = next(act for act in bar.actions() if act.text().replace("&", "") == "File")
        file_menu = file_menu_action.menu()
        actions = file_menu.actions()
        new_act = next(a for a in actions if a.text().replace("&", "") == "New Project...")
        open_act = next(a for a in actions if a.text().replace("&", "") == "Open Project...")
        save_act = next(a for a in actions if a.text().replace("&", "") == "Save Project")
        exit_act = next(a for a in actions if a.text().replace("&", "") == "Exit")
        new_act.trigger()
        open_act.trigger()
        assert captured["new"]
        assert captured["open"]
        assert not save_act.isEnabled()
        save_act.trigger()
        assert not captured["save"]
        bar.set_project_actions_enabled(True)
        assert save_act.isEnabled()
        save_act.trigger()
        assert captured["save"]
        exit_act.trigger()
        assert captured["exit"]

    def test_set_project_actions_enabled(self, tmp_path, monkeypatch, qapp):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(menu_bar, 'SETTINGS_FILE_NAME', str(settings_file))
        settings_file.write_text(json.dumps({}))
        parent = QtWidgets.QWidget()
        parent.close = lambda: None
        bar = AppMenuBar(parent)
        assert not bar.save_action.isEnabled()
        bar.set_project_actions_enabled(True)
        assert bar.save_action.isEnabled()
        bar.set_project_actions_enabled(False)
        assert not bar.save_action.isEnabled()

    def test_placeholder_action_logs_to_console(self, tmp_path, monkeypatch, qapp):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(menu_bar, 'SETTINGS_FILE_NAME', str(settings_file))
        settings_file.write_text(json.dumps({}))
        parent = QtWidgets.QWidget()
        logs = []
        parent.console_widget = type("C", (), {})()
        parent.console_widget.log_message = lambda msg: logs.append(msg)
        fake_act = QtGui.QAction()
        fake_act.setText("&TestAction")
        parent.sender = lambda: fake_act
        bar = AppMenuBar(parent)
        bar.placeholder_action()
        assert logs == ["Action 'TestAction' triggered (placeholder)."]

    def test_handle_settings_saved_updates_settings_and_file(self, tmp_path, monkeypatch, qapp):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(menu_bar, 'SETTINGS_FILE_NAME', str(settings_file))
        settings_file.write_text(json.dumps({}))
        parent = QtWidgets.QWidget()
        parent.close = lambda: None
        bar = AppMenuBar(parent)
        captured = []
        bar.settings_updated.connect(lambda s: captured.append(s))
        new_settings = {
            "OPENAI_API_KEY": "a",
            "GOOGLE_AI_STUDIO_API_KEY": "b",
            "Selected Inference Provider": AIModel.GOOGLEAI.name,
            "OPENAI_TEXT_MODEL": "openai-text",
            "OPENAI_IMAGE_MODEL": "openai-image",
            "GOOGLE_TEXT_MODEL": "google-text",
            "GOOGLE_IMAGE_MODEL": "google-image",
        }
        bar._handle_settings_saved(new_settings)
        assert captured and captured[0] == new_settings
        assert bar.current_app_settings == new_settings
        saved = json.loads(settings_file.read_text())
        assert saved == new_settings

    def test_open_settings_dialog_invokes_dialog(self, tmp_path, monkeypatch, qapp):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(menu_bar, 'SETTINGS_FILE_NAME', str(settings_file))
        settings_file.write_text(json.dumps({}))
        parent = QtWidgets.QWidget()
        parent.close = lambda: None
        bar = AppMenuBar(parent)
        instantiated = []
        connect_calls = []
        exec_calls = []
        class DummySignal:
            def __init__(self):
                self._cbs = []
            def connect(self, cb):
                self._cbs.append(cb)
                connect_calls.append(cb)
            def emit(self, *args, **kwargs):
                pass
        class DummyDialog:
            def __init__(self, curr, pr):
                instantiated.append((curr, pr))
                self.settings_saved = DummySignal()
            def exec(self):
                exec_calls.append(True)
        monkeypatch.setattr(menu_bar, 'SettingsDialog', DummyDialog)
        bar._open_settings_dialog()
        assert instantiated == [(bar.current_app_settings, parent)]
        assert len(connect_calls) == 1
        assert exec_calls == [True]

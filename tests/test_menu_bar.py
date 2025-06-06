import importlib
import json
import pytest
from PySide6 import QtWidgets, QtGui

import menu_bar
from menu_bar import SettingsDialog, AppMenuBar
from inference import AIModel

@pytest.fixture(scope='session', autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app

def test_import_menu_bar():
    module = importlib.import_module('menu_bar')
    assert module is not None

class TestSettingsDialog:

    def test_load_default_settings(self, qapp):
        dialog = SettingsDialog({}, parent=None)
        assert dialog.openai_api_key_input.text() == ""
        assert dialog.google_api_key_input.text() == ""
        # Only OPENAI selected by default
        for model, btn in dialog.inference_radio_buttons.items():
            if model == AIModel.OPENAI:
                assert btn.isChecked()
            else:
                assert not btn.isChecked()

    def test_load_selected_model(self, qapp):
        settings = {
            "OPENAI_API_KEY": "key1",
            "GOOGLE_AI_STUDIO_API_KEY": "key2",
            "Selected Inference Provider": AIModel.GOOGLEAI.name
        }
        dialog = SettingsDialog(settings, parent=None)
        assert dialog.openai_api_key_input.text() == "key1"
        assert dialog.google_api_key_input.text() == "key2"
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
        # Fallback to first radio button
        first_model = next(iter(dialog.inference_radio_buttons))
        for model, btn in dialog.inference_radio_buttons.items():
            if model == first_model:
                assert btn.isChecked()
            else:
                assert not btn.isChecked()

    def test_save_settings_emits_signal(self, qapp):
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
        assert saved["Selected Inference Provider"] == AIModel.TESTING.name

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
            "Selected Inference Provider": AIModel.GOOGLEAI.name
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

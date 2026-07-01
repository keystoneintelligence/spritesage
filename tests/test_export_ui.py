import os

import pytest
from PySide6 import QtWidgets

from spritesage import config, export_ui


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class DummyExportWidget(export_ui.GodotExportUiMixin, QtWidgets.QWidget):
    def __init__(self, project_dir, palette=None):
        super().__init__()
        self.project_dir = project_dir
        self.app_palette = palette or config.APP_PALETTE

    def _godot_export_project_directory(self) -> str:
        return self.project_dir


def test_godot_export_project_directory_must_be_implemented():
    with pytest.raises(NotImplementedError):
        export_ui.GodotExportUiMixin()._godot_export_project_directory()


def test_resolve_godot_export_dir_uses_shared_exports_folder(tmp_path):
    widget = DummyExportWidget(str(tmp_path))

    assert widget._resolve_godot_export_dir("hero") == os.path.join(
        str(tmp_path),
        "exports",
        "hero",
    )


def test_create_export_folder_dialog_uses_shared_popup_style(tmp_path):
    widget = DummyExportWidget(str(tmp_path))

    dialog = widget._create_export_folder_dialog("hero_godot_export")
    label = dialog.findChild(QtWidgets.QLabel)
    line_edit = dialog.lineEdit()

    assert dialog.windowTitle() == "Godot Export Folder"
    assert dialog.textValue() == "hero_godot_export"
    assert label is not None
    assert label.text() == "Folder name:"
    assert line_edit is not None
    assert line_edit.text() == "hero_godot_export"
    assert "QDialog#SpriteSagePopupDialog QLabel" in dialog.styleSheet()
    assert config.APP_PALETTE["editable_value_bg"] in line_edit.styleSheet()
    assert config.APP_PALETTE["text_color"] in line_edit.styleSheet()


def test_prompt_for_export_folder_name_reports_acceptance(monkeypatch, tmp_path):
    widget = DummyExportWidget(str(tmp_path))

    class FakeDialog:
        def __init__(self, result):
            self.result = result

        def exec(self):
            return self.result

        def textValue(self):
            return "hero"

    monkeypatch.setattr(
        widget,
        "_create_export_folder_dialog",
        lambda default: FakeDialog(QtWidgets.QDialog.DialogCode.Accepted),
    )
    assert widget._prompt_for_export_folder_name("default") == ("hero", True)

    monkeypatch.setattr(
        widget,
        "_create_export_folder_dialog",
        lambda default: FakeDialog(QtWidgets.QDialog.DialogCode.Rejected),
    )
    assert widget._prompt_for_export_folder_name("default") == ("hero", False)


def test_show_export_message_uses_palette_and_executes(monkeypatch, tmp_path):
    widget = DummyExportWidget(str(tmp_path))
    created_boxes = []

    class FakeMessageBox:
        class StandardButton:
            Ok = "ok"

        def __init__(self, parent=None):
            self.parent = parent
            self.icon = None
            self.title = ""
            self.text = ""
            self.buttons = None
            self.stylesheet = ""
            self.executed = False
            created_boxes.append(self)

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setStandardButtons(self, buttons):
            self.buttons = buttons

        def setStyleSheet(self, stylesheet):
            self.stylesheet = stylesheet

        def exec(self):
            self.executed = True

    monkeypatch.setattr(export_ui, "QMessageBox", FakeMessageBox)

    widget._show_export_message("info", "Export Complete", "Exported hero")

    assert len(created_boxes) == 1
    box = created_boxes[0]
    assert box.parent is widget
    assert box.icon == "info"
    assert box.title == "Export Complete"
    assert box.text == "Exported hero"
    assert box.buttons == FakeMessageBox.StandardButton.Ok
    assert "QMessageBox QLabel" in box.stylesheet
    assert f"background-color: {config.APP_PALETTE['dialog_bg']};" in box.stylesheet
    assert f"color: {config.APP_PALETTE['text_color']};" in box.stylesheet
    assert box.executed

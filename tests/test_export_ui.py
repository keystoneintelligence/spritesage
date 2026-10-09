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
    line_edit.ensurePolished()
    assert line_edit.palette().color(line_edit.palette().ColorRole.Base).name().lower() == (
        config.APP_PALETTE["editable_value_bg"].lower()
    )
    line_edit.ensurePolished()
    assert line_edit.palette().color(line_edit.palette().ColorRole.Text).name().lower() == (
        config.APP_PALETTE["text_color"].lower()
    )


def test_prompt_for_export_folder_name_reports_acceptance(monkeypatch, tmp_path):
    widget = DummyExportWidget(str(tmp_path))

    class FakeDialog:
        def __init__(self, result):
            self.result = result

        def exec(self):
            return self.result

        def textValue(self):
            return "hero"

        def selected_directory(self):
            return None

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

        def setObjectName(self, name):
            self.object_name = name

        def setPalette(self, palette):
            self.palette = palette

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


def test_confirmation_skips_first_exports_and_lists_actual_conflicting_values(
    monkeypatch, tmp_path
):
    from spritesage.godot_export_transaction import ExportPlan

    widget = DummyExportWidget(str(tmp_path))
    created = []
    buttons = []

    class FakeMessageBox:
        Icon = QtWidgets.QMessageBox.Icon
        StandardButton = QtWidgets.QMessageBox.StandardButton

        def __init__(self, parent):
            created.append(self)

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, value):
            self.text = value

        def setTextFormat(self, value):
            pass

        def setInformativeText(self, value):
            self.details = value

        def setDetailedText(self, value):
            self.file_details = value

        def setStandardButtons(self, value):
            self.buttons = value

        def setDefaultButton(self, value):
            self.default = value

        def button(self, value):
            return self

        def setText_for_button(self, value):
            buttons.append(value)

        def exec(self):
            return self.StandardButton.Cancel

    monkeypatch.setattr(export_ui, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(export_ui, "style_popup_dialog", lambda box, palette: None)
    plan = ExportPlan(root=tmp_path, creations=["New: create Godot asset"])
    assert widget._confirm_godot_export(plan)
    assert created == []
    plan.updates = ["attack: fps: 8.0 → 12.5"]
    plan.conflicts = list(plan.updates)
    plan.notices = ["Preserved scripts, collision shapes and metadata."]
    plan.file_diffs[tmp_path / "frames.tres"] = "Timing resource diff"
    assert not widget._confirm_godot_export(plan)
    box = created[0]
    assert "8.0 → 12.5" in box.details
    assert "Changed in both SpriteSage and Godot" in box.details
    assert "New: create Godot asset" in box.details
    assert "Preservation notes" not in box.details
    assert plan.notices[0] not in box.details
    assert "Preservation notes" not in box.file_details
    assert plan.notices[0] not in box.file_details
    assert "Timing resource diff" in box.file_details
    assert box.default == FakeMessageBox.StandardButton.Cancel


def test_export_cancel_leaves_all_files_untouched(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from spritesage.godot_export_transaction import ExportPlan

    widget = DummyExportWidget(str(tmp_path))
    path = tmp_path / "frames.tres"
    path.write_bytes(b"original")
    plan = ExportPlan(
        root=tmp_path,
        writes={path: b"replacement"},
        guards={path: b"original"},
        updates=["attack: replace frame 3 image"],
    )
    exporter = SimpleNamespace(prepare=lambda: plan)
    monkeypatch.setattr(widget, "_confirm_godot_export", lambda plan: False)
    calls = []

    def runner(parent, fn, **kwargs):
        calls.append(kwargs["message"])
        return fn()

    assert widget._run_godot_export(exporter, runner) is None
    assert calls == ["Reviewing Godot changes"]
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_first_export_does_not_open_update_dialog(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from spritesage.godot_export_transaction import ExportPlan

    widget = DummyExportWidget(str(tmp_path))
    path = tmp_path / "new.tscn"
    plan = ExportPlan(
        root=tmp_path,
        writes={path: b"new"},
        guards={path: None},
        creations=["New: create Godot asset"],
        exported_dirs=[tmp_path],
    )
    exporter = SimpleNamespace(prepare=lambda: plan)

    def fail_dialog(*args):
        raise AssertionError("A first export must not open an update confirmation")

    monkeypatch.setattr(export_ui, "QMessageBox", fail_dialog)
    assert widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn()) == [tmp_path]
    assert path.read_bytes() == b"new"


def test_noop_export_reports_up_to_date_without_writes(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from spritesage.godot_export_transaction import ExportPlan

    widget = DummyExportWidget(str(tmp_path))
    exporter = SimpleNamespace(prepare=lambda: ExportPlan(root=tmp_path))
    messages = []
    monkeypatch.setattr(widget, "_show_export_message", lambda *args: messages.append(args))
    assert widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn()) is None
    assert "already up to date" in messages[0][2]
    assert list(tmp_path.iterdir()) == []


def test_dialog_browses_direct_destination_and_remembers_only_after_success(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from spritesage.godot_export_transaction import ExportPlan

    widget = DummyExportWidget(str(tmp_path))
    destination = tmp_path / "godot" / "assets"
    destination.mkdir(parents=True)
    dialog = widget._create_export_folder_dialog("hero_godot_export")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getExistingDirectory", lambda *args: str(destination)
    )
    dialog._browse()
    assert dialog.selected_directory() == str(destination.resolve())
    dialog.lineEdit().setText("hero")
    assert dialog.destination_edit.text() == str(destination.resolve())
    monkeypatch.setattr(dialog, "exec", lambda: QtWidgets.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(widget, "_create_export_folder_dialog", lambda default: dialog)
    assert widget._prompt_for_export_folder_name("hero_godot_export") == ("hero", True)
    assert widget._resolve_godot_export_dir("hero") == str(destination.resolve())
    preferences = tmp_path / ".spritesage-godot-destinations.json"
    assert not preferences.exists()
    path = destination / "Hero.tscn"
    plan = ExportPlan(
        root=destination,
        writes={path: b"new"},
        guards={path: None},
        creations=["Hero"],
        exported_dirs=[destination],
    )
    exporter = SimpleNamespace(prepare=lambda: plan)
    widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn())
    reopened = DummyExportWidget(str(tmp_path))._create_export_folder_dialog("hero_godot_export")
    assert reopened.selected_directory() == str(destination.resolve())


def test_cancelled_destination_dialog_cannot_override_next_export(monkeypatch, tmp_path):
    widget = DummyExportWidget(str(tmp_path))
    dialog = widget._create_export_folder_dialog("hero")
    dialog.custom_destination = str(tmp_path / "other")
    monkeypatch.setattr(dialog, "exec", lambda: QtWidgets.QDialog.DialogCode.Rejected)
    monkeypatch.setattr(widget, "_create_export_folder_dialog", lambda default: dialog)
    widget._godot_selected_destination = str(tmp_path / "previous")
    assert widget._prompt_for_export_folder_name("hero") == ("hero", False)
    assert widget._resolve_godot_export_dir("hero") == str(tmp_path / "exports" / "hero")
    assert not widget._godot_destination_preferences().exists()


def test_remembered_destination_can_return_to_project_folder(monkeypatch, tmp_path):
    import json

    widget = DummyExportWidget(str(tmp_path))
    preferences = tmp_path / ".spritesage-godot-destinations.json"
    preferences.write_text(json.dumps({"hero": str(tmp_path / "godot")}))
    dialog = widget._create_export_folder_dialog("hero")
    assert not dialog.lineEdit().isEnabled()
    dialog._use_project_exports()
    assert dialog.lineEdit().isEnabled()
    assert dialog.selected_directory() is None
    dialog.lineEdit().setText("fresh_export")
    assert dialog.destination_edit.text() == str(tmp_path / "exports" / "fresh_export")
    monkeypatch.setattr(dialog, "exec", lambda: QtWidgets.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(widget, "_create_export_folder_dialog", lambda default: dialog)
    assert widget._prompt_for_export_folder_name("hero") == ("fresh_export", True)
    widget._remember_godot_destination()
    assert "hero" not in json.loads(preferences.read_bytes())


@pytest.mark.parametrize("accept", [False, True])
def test_model_frame_deletion_runs_confirmation_and_respects_choice(monkeypatch, tmp_path, accept):
    from PIL import Image
    from spritesage.exporter import GodotSpriteExporter
    from spritesage.sprite_file import Animation, SpriteFile
    from spritesage import godot_text

    frames = []
    for index in range(3):
        path = tmp_path / f"model-frame-{index}.png"
        image = Image.new("RGBA", (8, 8))
        image.putpixel((index, 1), (50, 80, 100, 128))
        image.save(path)
        frames.append(str(path))
    sprite = SpriteFile(
        "model-id",
        "Model",
        "",
        8,
        8,
        frames[0],
        {"walk": Animation("walk", frames, 10, False)},
        include_base_image_in_animations=False,
    )
    destination = tmp_path / "godot"
    GodotSpriteExporter(sprite, str(destination)).export()
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in destination.iterdir()
    }
    sprite.animations["walk"].select_frames([0, 2])
    widget = DummyExportWidget(str(tmp_path))
    reviewed = []

    def confirm(plan):
        reviewed.append(plan)
        assert any("frame count: 3 → 2" in update for update in plan.updates)
        assert plan.notices
        return accept

    monkeypatch.setattr(widget, "_confirm_godot_export", confirm)
    result = widget._run_godot_export(
        GodotSpriteExporter(sprite, str(destination)), lambda parent, fn, **kwargs: fn()
    )
    assert len(reviewed) == 1
    if accept:
        assert result == [destination]
        resource = (destination / "Model_frames.tres").read_text()
        assert (
            len(godot_text.items(resource, godot_text.animations(resource)["walk"]["frames"])) == 2
        )
        assert (destination / "Model.tscn").read_bytes() == before["Model.tscn"][0]
        assert (destination / "Model_sheet.png").read_bytes() == before["Model_sheet.png"][0]
    else:
        assert result is None
        assert {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in destination.iterdir()
        } == before

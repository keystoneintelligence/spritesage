import json

import pytest
from PySide6 import QtWidgets

from spritesage import config, persistence
from spritesage.editor import EditorWidget
from spritesage.menu_bar import AppMenuBar, SettingsDialog
from spritesage.persistence import damaged_path, save_document, recovery_path
from spritesage.settings import SettingsError


@pytest.fixture(scope="session", autouse=True)
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "project.sage"
    save_document(path, {"Project Name": "Example", "Project Description": "first"})
    return path


def recovery_menu(widget):
    bar = AppMenuBar(widget, initial_settings={})
    widget.recovery_available_changed.connect(bar.recover_action.setEnabled)
    bar.recover_saved_version_requested.connect(widget.recover_saved_version)
    return bar


def test_autosave_checkpoint_survives_reopening_and_recovery_is_undoable(document, monkeypatch):
    widget = EditorWidget(config.APP_PALETTE)
    bar = recovery_menu(widget)
    widget.load_file(str(document))
    assert widget.save_status.isHidden()
    assert not bar.recover_action.isEnabled()
    assert not any(
        "Recover" in button.text() or "Restore" in button.text()
        for button in widget.findChildren(QtWidgets.QPushButton)
    )
    widget.sage_editor._widgets["Project Description"].setText("second")
    assert json.loads(document.read_text())["Project Description"] == "second"
    assert widget.save_status.isHidden()
    assert bar.recover_action.isEnabled()
    widget.sage_editor._widgets["Project Description"].setText("third")
    widget.save()
    assert json.loads(recovery_path(document).read_text())["Project Description"] == "first"
    monkeypatch.setattr(persistence, "_session_checkpoints", set())  # Simulate restarting the app.
    reopened = EditorWidget(config.APP_PALETTE)
    reopened_bar = recovery_menu(reopened)
    reopened.load_file(str(document))
    assert reopened_bar.recover_action.isEnabled()
    prompts = []

    def confirm(*args):
        prompts.append(args[2])
        return QtWidgets.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", confirm)
    reopened_bar.recover_action.trigger()
    assert "Checkpoint saved:" in prompts[0] and "Use Undo/Redo for recent edits" in prompts[0]
    assert "Edit → Undo" in prompts[0]
    assert json.loads(document.read_text())["Project Description"] == "first"
    assert reopened.sage_editor._widgets["Project Description"].text() == "first"
    assert reopened.undo_redo_state().undo_text == "Recover saved version"
    assert reopened.save_status.isHidden()
    reopened.undo()
    assert json.loads(document.read_text())["Project Description"] == "third"
    reopened.redo()
    assert json.loads(document.read_text())["Project Description"] == "first"
    assert json.loads(recovery_path(document).read_text())["Project Description"] == "first"


def test_failed_autosave_keeps_edits_visible_and_blocks_navigation(document, monkeypatch):
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    before = document.read_bytes()
    real_write = persistence.atomic_write
    monkeypatch.setattr(
        persistence, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    field = widget.sage_editor._widgets["Project Description"]
    field.setText("unsaved work")
    assert document.read_bytes() == before
    assert field.text() == "unsaved work"
    assert widget.save_status.text().startswith("Save failed")
    assert not widget.save_status.isHidden()
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: warnings.append(a))
    widget.load_file(None)
    assert widget.current_file_path == str(document)
    assert warnings
    monkeypatch.setattr(persistence, "atomic_write", real_write)
    assert widget.save() is True
    assert widget.save_status.isHidden()
    assert json.loads(document.read_text())["Project Description"] == "unsaved work"


def test_recovery_preserves_earlier_undo_history_and_checkpoint_on_file_switch(
    document, monkeypatch
):
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    widget.sage_editor._widgets["Project Description"].setText("second")
    widget.load_file(None)
    widget.load_file(str(document))
    widget.sage_editor._widgets["Project Description"].setText("third")
    widget.sage_editor._widgets["Keywords"].setText("forest")
    assert widget.undo_redo_state().undo_count == 2
    checkpoint = recovery_path(document).read_bytes()
    assert json.loads(checkpoint)["Project Description"] == "first"
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    widget.recover_saved_version()
    assert widget.undo_redo_state().undo_count == 3
    widget.undo()
    assert widget.sage_editor._widgets["Keywords"].text() == "forest"
    assert widget.sage_editor._widgets["Project Description"].text() == "third"
    widget.undo()
    assert widget.sage_editor._widgets["Keywords"].text() == ""
    assert widget.sage_editor._widgets["Project Description"].text() == "third"
    widget.undo()
    assert widget.sage_editor._widgets["Project Description"].text() == "second"
    assert recovery_path(document).read_bytes() == checkpoint


def test_failed_recovery_keeps_unsaved_work_and_history(document, monkeypatch):
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    widget.sage_editor._widgets["Project Description"].setText("second")
    before = document.read_bytes()
    checkpoint = recovery_path(document).read_bytes()
    history = widget.undo_redo_state()
    monkeypatch.setattr(
        persistence, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    widget.sage_editor._widgets["Project Description"].setText("unsaved work")
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: warnings.append(a))
    widget.recover_saved_version()
    assert warnings[0][1] == "Recovery failed"
    assert document.read_bytes() == before
    assert recovery_path(document).read_bytes() == checkpoint
    assert widget.undo_redo_state() == history
    assert widget.sage_editor._widgets["Project Description"].text() == "unsaved work"
    assert widget.save_status.text().startswith("Save failed")
    assert not widget.save_status.isHidden()
    assert not widget.finish_pending_save()


def test_recovery_of_unsaved_edits_can_be_undone(document, monkeypatch):
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    widget.sage_editor._widgets["Project Description"].setText("second")
    with monkeypatch.context() as context:
        context.setattr(persistence, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError()))
        widget.sage_editor._widgets["Project Description"].setText("unsaved work")
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    widget.recover_saved_version()
    assert widget.sage_editor._widgets["Project Description"].text() == "first"
    widget.undo()
    assert widget.sage_editor._widgets["Project Description"].text() == "unsaved work"
    assert json.loads(document.read_text())["Project Description"] == "unsaved work"


@pytest.mark.parametrize("corrupt_content", ["corrupt", "[]", "null"])
def test_corrupt_project_recovery_and_menu_action(document, monkeypatch, corrupt_content):
    save_document(document, {"Project Name": "Example", "Project Description": "second"})
    document.write_text(corrupt_content)
    widget = EditorWidget(config.APP_PALETTE)
    bar = recovery_menu(widget)
    widget.load_file(str(document))
    assert widget.save_status.text() == "Could not open document"
    assert not widget.save_status.isHidden()
    assert bar.recover_action.isEnabled()
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    bar.recover_action.trigger()
    assert json.loads(document.read_text())["Project Description"] == "first"
    assert widget.save_status.isHidden()
    assert damaged_path(document).read_text() == corrupt_content
    assert not widget.undo_redo_state().can_undo
    widget.clear_editor()
    assert not bar.recover_action.isEnabled()


def test_cancel_restore_keeps_document(document, monkeypatch):
    save_document(document, {"Project Name": "Example", "Project Description": "second"})
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.No
    )
    widget.recover_saved_version()
    assert json.loads(document.read_text())["Project Description"] == "second"


def test_damaged_sprite_schema_is_preserved_before_recovery(document, monkeypatch):
    sprite = document.with_suffix(".sprite")
    save_document(sprite, {**config.EMPTY_SPRITE_TEMPLATE, "uuid": "hero", "name": "first"})
    save_document(sprite, {**config.EMPTY_SPRITE_TEMPLATE, "uuid": "hero", "name": "second"})
    sprite.write_text('{"name": "missing required fields"}')
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: None)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    widget = EditorWidget(config.APP_PALETTE)
    widget.load_file(str(document))
    widget.load_file(str(sprite))
    assert widget.current_file_path is None
    widget.recover_saved_version()
    assert widget.sprite_editor.name_edit.text() == "first"
    assert json.loads(damaged_path(sprite).read_text()) == {"name": "missing required fields"}
    assert not widget.undo_redo_state().can_undo


def test_preferences_failure_keeps_dialog_open_and_does_not_emit(tmp_path, monkeypatch, capsys):
    parent = QtWidgets.QWidget()
    bar = AppMenuBar(
        parent, settings_file_path=str(tmp_path / "preferences.json"), initial_settings={}
    )
    dialog = SettingsDialog({})
    dialog.persist_settings = bar._handle_settings_saved
    dialog.openai_api_key_input.setText("private-secret")
    monkeypatch.setattr(
        bar.settings_store,
        "save",
        lambda *a: (_ for _ in ()).throw(SettingsError("OS credential store is locked")),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: None)
    emitted = []
    dialog.settings_saved.connect(emitted.append)
    dialog.save_settings()
    assert not emitted and not bar.current_app_settings
    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.openai_api_key_input.text() == "private-secret"
    assert "private-secret" not in capsys.readouterr().out


def test_sprite_autosave_uses_recovery_without_resaving_inactive_sprite(document, monkeypatch):
    sprite = document.with_suffix(".sprite")
    save_document(sprite, {**config.EMPTY_SPRITE_TEMPLATE, "uuid": "hero", "name": "first"})
    widget = EditorWidget(config.APP_PALETTE)
    bar = recovery_menu(widget)
    widget.load_file(str(document))
    widget.load_file(str(sprite))
    widget.sprite_editor.name_edit.setText("second")
    assert json.loads(sprite.read_text())["name"] == "second"
    assert widget.save_status.isHidden()
    assert bar.recover_action.isEnabled()
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes
    )
    previous_history = widget.undo_redo_state().undo_count
    widget.recover_saved_version()
    assert widget.sprite_editor.name_edit.text() == "first"
    assert widget.undo_redo_state().undo_count == previous_history + 1
    assert widget.undo_redo_state().undo_text == "Recover saved version"
    widget.undo()
    assert widget.sprite_editor.name_edit.text() == "second"
    widget.redo()
    assert widget.sprite_editor.name_edit.text() == "first"
    assert json.loads(recovery_path(sprite).read_text())["name"] == "first"
    widget.load_file(str(document))
    save_document(sprite, {**config.EMPTY_SPRITE_TEMPLATE, "uuid": "hero", "name": "external"})
    widget.save()
    assert json.loads(sprite.read_text())["name"] == "external"

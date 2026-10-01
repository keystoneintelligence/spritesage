"""Offline regressions for blank references and persistent generation errors."""

import base64
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from spritesage import inference, utils
from spritesage.config import EMPTY_SAGE_TEMPLATE
from spritesage.persistence import save_document
from spritesage.sage_file import SageFile


@pytest.fixture(scope="session", autouse=True)
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_fresh_project_keeps_empty_reference_slots_across_saves(tmp_path):
    path = tmp_path / "new-project.sage"
    data = deepcopy(EMPTY_SAGE_TEMPLATE)
    assert data["Reference Images"] == ["", "", "", ""]
    save_document(path, data)

    for _ in range(3):
        project = SageFile.from_json(str(path))
        assert project.reference_images == ["", "", "", ""]
        assert project.reference_image_abs_paths() == []
        assert project.to_dict()["Reference Images"] == ["", "", "", ""]
        project.save()


@pytest.mark.parametrize("legacy_path", ["", ".", "./", "absolute-directory"])
def test_legacy_empty_slots_are_normalized_without_losing_valid_references(tmp_path, legacy_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    if legacy_path == "absolute-directory":
        legacy_path = str(tmp_path)
    project = SageFile.from_dict(
        {"Reference Images": [legacy_path, "reference.png", "", "."]},
        str(tmp_path / "project.sage"),
    )
    assert project.reference_images == ["", str(image), "", ""]
    assert project.reference_image_abs_paths() == [str(image)]
    assert project.reference_image_abs_paths(exclude_index=1) == []
    assert project.to_dict()["Reference Images"] == ["", "reference.png", "", ""]

    # Also normalize a project-directory path already in memory from an older load.
    project.reference_images[0] = str(tmp_path)
    assert project.to_dict()["Reference Images"][0] == ""


@pytest.mark.parametrize("with_reference", [False, True])
def test_openai_never_opens_empty_or_directory_references(tmp_path, monkeypatch, with_reference):
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    calls = []
    opened = []
    result = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"output").decode())])

    def generate(**kwargs):
        calls.append("generate")
        return result

    def edit(**kwargs):
        calls.append("edit")
        opened.extend(kwargs["image"])
        assert [file.name for file in kwargs["image"]] == [str(image)]
        return result

    monkeypatch.setattr(
        inference, "openai", SimpleNamespace(images=SimpleNamespace(generate=generate, edit=edit))
    )
    references = ["", str(tmp_path), str(tmp_path / ".")]
    if with_reference:
        references.append(str(image))
    client = inference.OpenAIClient()
    output = client.generate_base_sprite_image(
        inference.GenerateBaseSpriteImageInput(
            str(tmp_path), "sprite", "project", "", references, ""
        )
    )
    assert calls == ["edit" if with_reference else "generate"]
    assert output is not None
    assert Path(output).read_bytes() == b"output"
    assert all(file.closed for file in opened)


@pytest.mark.parametrize(
    "provider", [inference.AIModel.OPENAI, inference.AIModel.GOOGLEAI, inference.AIModel.LOCAL]
)
def test_generation_error_stays_visible_until_acknowledged(qapp, monkeypatch, provider):
    manager = SimpleNamespace(get_active_vendor=lambda: provider)
    parent = QtWidgets.QWidget()
    error_text = "Permission denied: project folder <details>"
    observations = []

    def fail():
        raise PermissionError(error_text)

    if provider == inference.AIModel.LOCAL:
        from modelmanager import qt

        monkeypatch.setattr(qt, "run_task", lambda *args: fail())

    timer = QtCore.QTimer()

    def inspect_dialog():
        box = qapp.activeModalWidget()
        if not isinstance(box, QtWidgets.QMessageBox):
            return
        observations.append(
            (
                box.isVisible(),
                box.text(),
                box.textFormat(),
                box.standardButtons(),
                QtCore.QThread.currentThread() == qapp.thread(),
                all(
                    not child.isVisible()
                    for child in parent.findChildren(QtWidgets.QDialog)
                    if child is not box
                ),
            )
        )
        if len(observations) == 3:
            box.button(QtWidgets.QMessageBox.StandardButton.Ok).click()

    timer.timeout.connect(inspect_dialog)
    timer.start(40)
    try:
        assert utils.call_ai_with_busy(parent, manager, fail, message="Generating image") is None
    finally:
        timer.stop()
        parent.close()

    assert len(observations) == 3
    for visible, text, text_format, buttons, gui_thread, progress_closed in observations:
        assert visible
        assert error_text in text
        assert text_format == QtCore.Qt.TextFormat.PlainText
        assert buttons == QtWidgets.QMessageBox.StandardButton.Ok
        assert gui_thread
        assert progress_closed


def test_empty_cloud_result_shows_error(qapp, monkeypatch):
    manager = SimpleNamespace(get_active_vendor=lambda: inference.AIModel.OPENAI)
    messages = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda box: messages.append(box.text()))
    assert utils.call_ai_with_busy(None, manager, lambda: None, message="Generating image") is None
    assert len(messages) == 1
    assert "provider returned no result" in messages[0]


@pytest.mark.parametrize("runner", [utils.call_with_busy, utils.call_with_progress])
def test_worker_errors_reach_gui_after_progress_closes(qapp, runner):
    def fail(**kwargs):
        raise PermissionError("Cannot write generated image")

    with pytest.raises(PermissionError, match="Cannot write generated image"):
        runner(None, fail)


@pytest.mark.parametrize(
    "method_name", ["generate_next_sprite_image", "generate_sprite_between_images"]
)
def test_missing_animation_reference_fails_before_api_call(tmp_path, monkeypatch, method_name):
    def unexpected_request(**kwargs):
        pytest.fail("Missing animation references must not start a paid image request")

    monkeypatch.setattr(
        inference,
        "openai",
        SimpleNamespace(
            images=SimpleNamespace(generate=unexpected_request, edit=unexpected_request)
        ),
    )
    if method_name == "generate_next_sprite_image":
        input = inference.GenerateNextSpriteImageInput(str(tmp_path), "walk", str(tmp_path), "")
    else:
        input = inference.GenerateSpriteBetweenImagesInput(
            str(tmp_path), "walk", [str(tmp_path / "missing.png")], ""
        )
    with pytest.raises(ValueError, match="Choose existing image files"):
        getattr(inference.OpenAIClient(), method_name)(input)

import pytest
from PySide6 import QtWidgets

from spritesage import inference
from spritesage import utils


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_ensure_llm_configured_opens_settings_on_missing_config(monkeypatch):
    class DummyManager:
        def get_client(self):
            raise inference.MissingConfigurationException("missing config")

    calls = []
    monkeypatch.setattr(
        utils, "prompt_for_llm_settings", lambda parent, message: calls.append(message) or True
    )

    assert utils.ensure_llm_configured(None, DummyManager()) is False
    assert calls == ["missing config"]


def test_ensure_llm_configured_does_not_swallow_other_errors():
    class DummyManager:
        def get_client(self):
            raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        utils.ensure_llm_configured(None, DummyManager())


def test_ensure_llm_configured_accepts_configured_manager():
    class DummyManager:
        def get_client(self):
            return object()

    assert utils.ensure_llm_configured(None, DummyManager()) is True


def test_text_input_dialog_uses_shared_popup_style(qapp):
    dialog = utils.TextInputDialog(
        title="New Sprite",
        label_text="Enter sprite filename:",
        default_text="hero",
    )
    label = dialog.findChild(QtWidgets.QLabel)
    line_edit = dialog.lineEdit()

    assert dialog.objectName() == utils.POPUP_DIALOG_OBJECT_NAME
    assert dialog.textValue() == "hero"
    assert label is not None
    assert label.property("dialogTextPanel") is None
    assert "QDialog#SpriteSagePopupDialog QLineEdit" in dialog.styleSheet()
    assert utils.APP_PALETTE["editable_value_bg"] in line_edit.styleSheet()
    assert utils.APP_PALETTE["text_color"] in line_edit.styleSheet()


def test_call_with_busy_returns_none_result(qapp):
    calls = []

    def worker():
        calls.append("ran")
        return None

    assert utils.call_with_busy(None, worker, message="Working") is None
    assert calls == ["ran"]


def test_call_with_progress_returns_none_result(qapp):
    progress = []

    def worker(progress_callback=None):
        progress.append("ran")
        assert progress_callback is not None
        progress_callback(1, 1, "Done")
        return None

    assert utils.call_with_progress(None, worker, message="Working") is None
    assert progress == ["ran"]

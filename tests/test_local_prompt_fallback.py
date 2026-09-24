from types import SimpleNamespace

from modelmanager.enhancer import EnhancementError
from modelmanager import Cancelled
from spritesage import utils
from spritesage.inference import AIModel


def test_explicit_original_prompt_retry_does_not_change_saved_settings(monkeypatch):
    from modelmanager import qt

    settings = {"LOCAL_GENERATION": {"enhance_prompts": True}}
    manager = SimpleNamespace(get_active_vendor=lambda: AIModel.LOCAL, config_data=settings)
    failure = EnhancementError("No completed rewrite")
    failure.generate_original = lambda progress, cancel: "original-result.png"
    calls = []

    def run(parent, title, task, palette):
        calls.append(task)
        if len(calls) == 1:
            raise failure
        return task(None, None)

    class Dialog:
        ButtonRole = utils.QMessageBox.ButtonRole
        StandardButton = utils.QMessageBox.StandardButton

        def __init__(self, parent):
            self.original = None

        def setWindowTitle(self, value):
            pass

        def setText(self, value):
            pass

        def addButton(self, label, *args):
            button = object()
            if label == "Generate with original prompt":
                self.original = button
            return button

        def exec(self):
            pass

        def clickedButton(self):
            return self.original

    monkeypatch.setattr(qt, "run_task", run)
    monkeypatch.setattr(utils, "QMessageBox", Dialog)
    monkeypatch.setattr(utils, "style_popup_dialog", lambda *a: None)
    assert (
        utils.call_ai_with_busy(None, manager, lambda: None, message="Generate")
        == "original-result.png"
    )
    assert settings["LOCAL_GENERATION"]["enhance_prompts"]
    assert len(calls) == 2


def test_cancel_does_not_offer_original_prompt_fallback(monkeypatch):
    from modelmanager import qt

    manager = SimpleNamespace(get_active_vendor=lambda: AIModel.LOCAL)

    def run(*args):
        raise Cancelled("canceled")

    monkeypatch.setattr(qt, "run_task", run)
    monkeypatch.setattr(
        utils,
        "QMessageBox",
        lambda *a: (_ for _ in ()).throw(AssertionError("No fallback after cancellation")),
    )
    assert utils.call_ai_with_busy(None, manager, lambda: None, message="Generate") is None

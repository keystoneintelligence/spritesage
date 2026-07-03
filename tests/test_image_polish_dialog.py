from typing import Any, cast

import pytest
from PIL import Image
from PySide6 import QtWidgets

from spritesage import config
from spritesage.image_polish_dialog import ImagePolishDialog


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_dialog_initial_preview_does_not_run_background_cleanup(qapp, monkeypatch):
    calls = []

    def fake_polish_image(image, options):
        calls.append(options.clean_background)
        return image

    monkeypatch.setattr("spritesage.image_polish_dialog.polish_image", fake_polish_image)

    ImagePolishDialog(
        Image.new("RGBA", (2, 2), cast(Any, (255, 255, 255, 255))),
        palette=config.APP_PALETTE,
    )

    assert calls
    assert calls == [False]


def test_clean_background_button_runs_ben2_and_updates_working_image(qapp, monkeypatch):
    calls = []
    source = Image.new("RGBA", (2, 2), cast(Any, (255, 255, 255, 255)))
    cleaned = Image.new("RGBA", (2, 2), cast(Any, (0, 0, 0, 0)))
    cleaned.putpixel((1, 1), (10, 20, 30, 255))

    def fake_call_with_busy(parent, fn, **kwargs):
        calls.append(("busy", kwargs["message"]))
        return fn()

    def fake_clean_background(image):
        calls.append(("clean", image.mode))
        return cleaned

    monkeypatch.setattr("spritesage.image_polish_dialog.call_with_busy", fake_call_with_busy)
    monkeypatch.setattr(
        "spritesage.image_polish_dialog.clean_background_with_ben2",
        fake_clean_background,
    )

    dialog = ImagePolishDialog(source, palette=config.APP_PALETTE)
    dialog.trim_padding_check.setChecked(False)
    dialog.center_canvas_check.setChecked(False)
    dialog.clean_background_button.click()

    assert calls == [("busy", "Cleaning transparent background..."), ("clean", "RGBA")]
    assert dialog.working_image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert dialog.polished_image.getpixel((1, 1)) == (10, 20, 30, 255)

"""Guard theme ownership and Qt's effective popup colors, including inheritance."""

import ast
from pathlib import Path
import re

import pytest
from PySide6 import QtGui, QtWidgets

from spritesage import config, theme, utils
from spritesage.sprite_editor import SpriteEditorView
from spritesage.sprite_file import SpriteFile


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def color(widget, role):
    widget.ensurePolished()
    return widget.palette().color(role).name().lower()


def test_theme_is_only_source_of_gui_colors_and_stylesheets():
    root = Path(theme.__file__).parent
    for path in root.rglob("*.py"):
        if path.name == "theme.py":
            continue
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), path
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Widgets may apply a builder's result, but should not define QSS.
                assert not re.search(
                    r"(?:background(?:-color)?|color|border|padding|font-family)\s*:",
                    node.value,
                ), (path, node.lineno)


def test_compatibility_exports_share_theme_definitions():
    assert config.APP_PALETTE is theme.APP_PALETTE
    assert config.build_application_stylesheet is theme.build_application_stylesheet
    assert utils.style_popup_dialog is theme.style_popup_dialog


def test_partial_palette_resolves_aliases_without_mutating_defaults():
    overrides = {
        "widget_bg": theme.APP_PALETTE["canvas_bg"],
        "editable_value_bg": theme.APP_PALETTE["console_bg"],
        "text_color": theme.APP_PALETTE["table_header_fg"],
        "button_fg": theme.APP_PALETTE["tree_item_selected_text"],
    }
    resolved = theme.resolve_palette(overrides)
    assert resolved["dialog_bg"] == overrides["widget_bg"]
    assert resolved["dialog_input_bg"] == overrides["editable_value_bg"]
    assert resolved["dialog_input_fg"] == overrides["text_color"]
    assert resolved["button_text"] == overrides["button_fg"]
    assert "dialog_bg" not in overrides
    assert theme.APP_PALETTE["dialog_bg"] != resolved["dialog_bg"]


def test_all_stylesheet_builders_accept_partial_palettes():
    overrides = {"text_color": theme.APP_PALETTE["table_header_fg"]}
    for name, builder in vars(theme).items():
        if name.startswith("build_") and name.endswith("_stylesheet"):
            assert builder(overrides).strip(), name
    assert "italic" in theme.build_sage_value_stylesheet(overrides, is_locked=True)
    assert "solid" in theme.build_image_loader_stylesheet(overrides, border_style="solid")


def test_qt_palette_covers_disabled_and_placeholder_colors(qapp):
    palette = theme.build_qt_palette()
    for role in (QtGui.QPalette.ColorRole.Text, QtGui.QPalette.ColorRole.ButtonText):
        assert palette.color(QtGui.QPalette.ColorGroup.Disabled, role) == QtGui.QColor(
            theme.APP_PALETTE["disabled_fg"]
        )
    assert palette.color(QtGui.QPalette.ColorRole.PlaceholderText) == QtGui.QColor(
        theme.APP_PALETTE["placeholder_text"]
    )


@pytest.mark.parametrize("custom_palette", [False, True])
def test_add_animation_matches_other_popup_colors(qapp, monkeypatch, custom_palette):
    palette = (
        theme.APP_PALETTE
        if not custom_palette
        else {
            **theme.APP_PALETTE,
            "dialog_bg": theme.APP_PALETTE["window_bg"],
            "dialog_input_bg": theme.APP_PALETTE["canvas_bg"],
            "dialog_input_fg": theme.APP_PALETTE["table_header_fg"],
        }
    )
    editor = SpriteEditorView(palette)
    editor.current_file_path = "test.sprite"
    sprite = SpriteFile("test", "Hero", "", 32, 32, "", {})
    editor.sprite_data = sprite
    comparison = utils.TextInputDialog(
        editor, title="New Sprite", label_text="Other popup", palette=palette
    )
    comparison_label = comparison.findChild(QtWidgets.QLabel)
    assert comparison_label is not None
    comparison_edit = comparison.lineEdit()
    inspected = []

    def inspect_dialog(dialog):
        dialog.show()
        qapp.processEvents()
        labels = dialog.findChildren(QtWidgets.QLabel)
        assert {label.text() for label in labels} == {
            "Enter Animation Name:",
            "Add AI Generated Frames:",
        }
        for label in labels:
            assert label.property("dialogTextPanel") is None
            assert color(label, QtGui.QPalette.ColorRole.Window) == palette["dialog_bg"].lower()
            assert color(label, QtGui.QPalette.ColorRole.WindowText) == color(
                comparison_label, QtGui.QPalette.ColorRole.WindowText
            )
            # Rendered background must agree with Qt's effective palette too.
            assert label.grab().toImage().pixelColor(0, 0).name() == palette["dialog_bg"].lower()
        for field in dialog.findChildren(QtWidgets.QLineEdit):
            assert (
                color(field, QtGui.QPalette.ColorRole.Base)
                == color(comparison_edit, QtGui.QPalette.ColorRole.Base)
                == palette["dialog_input_bg"].lower()
            )
            assert color(field, QtGui.QPalette.ColorRole.Text) == palette["dialog_input_fg"].lower()
        for button in dialog.findChildren(QtWidgets.QPushButton):
            assert color(button, QtGui.QPalette.ColorRole.Button) == palette["button_bg"].lower()
        inspected.append(True)
        dialog.close()
        return QtWidgets.QDialog.DialogCode.Rejected

    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect_dialog)
    try:
        editor._add_animation()
        assert inspected == [True]
        assert sprite.animations == {}
    finally:
        editor.close()
        comparison.close()

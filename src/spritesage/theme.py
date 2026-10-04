"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)

The single source of GUI colors, Qt palettes, and widget styles.

Widgets choose a style and supply state; color and QSS definitions live here.
Use resolve_palette for partial overrides, including custom-painted canvases.
"""

from collections.abc import Mapping
from PySide6 import QtGui, QtWidgets

POPUP_DIALOG_OBJECT_NAME = "SpriteSagePopupDialog"

MIN_PANEL_WIDTH = 200
MIN_IMAGE_HEIGHT = 100
MIN_EDITOR_CONSOLE_WIDTH = 50
MIN_EDITOR_CONSOLE_HEIGHT = 30
SIDEBAR_ICON_SIZE = 12
SIDEBAR_DEPTH_COLORS = [
    QtGui.QColor("#3498db"),
    QtGui.QColor("#2ecc71"),
    QtGui.QColor("#f1c40f"),
    QtGui.QColor("#e67e22"),
    QtGui.QColor("#e74c3c"),
    QtGui.QColor("#9b59b6"),
    QtGui.QColor("#1abc9c"),
    QtGui.QColor("#7f8c8d"),
]

APP_PALETTE = {
    "window_bg": "#2B2B2B",
    "widget_bg": "#3C3F41",  # Used for general widget background AND editable fields in Sage view
    "text_color": "#BBBBBB",  # Used for general text AND editable field text
    "placeholder_bg": "#3C3F41",
    "placeholder_border": "#555555",  # Used for general borders AND field borders
    "console_bg": "#313335",
    "splitter_handle": "#555555",
    "button_bg": "#555555",
    "button_text": "#BBBBBB",
    "tree_bg": "#3C3F41",
    "tree_item_selected_bg": "#5A7E9E",
    "tree_item_selected_text": "#FFFFFF",
    "menu_bg": "#4F5254",
    "menu_text": "#BBBBBB",
    "dialog_bg": "#3C3F41",
    "dialog_input_bg": "#313335",
    "dialog_input_fg": "#BBBBBB",
    # Label color (key part): Slightly dimmer than main text
    "label_color": "#909090",
    # Background for locked value fields: Slightly darker/different shade than editable bg
    "locked_value_bg": "#3C3F41",  # Same as general widget bg in this case
    # Background for editable value fields: Slightly different for contrast
    "editable_value_bg": "#313335",  # Using console bg color for editable fields
    "canvas_bg": "#25282C",
    "checker_bg": "#30343A",
    "button_hover_bg": "#6A6A6A",
    "button_hover_border": "#777777",
    "button_pressed_bg": "#4E4E4E",
    "disabled_bg": "#404040",
    "disabled_fg": "#777777",
    "disabled_border": "#444444",
    "danger_bg": "#AA3333",
    "danger_hover_bg": "#CC4444",
    "danger_pressed_bg": "#882222",
    "tab_hover_bg": "#4A4D4F",
    "image_loader_bg": "#3A3A3A",
    "image_loader_border": "#666666",
    "placeholder_text": "#808080",
    "table_header_bg": "#4A4A4A",
    "table_header_fg": "#E0E0E0",
    "table_grid_color": "#555555",
    "table_alt_row_bg": "#404040",
    "list_alt_bg": "#3A3A3A",
}


def resolve_palette(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Merge defaults once; derive aliases from the effective semantic colors."""
    palette = APP_PALETTE.copy()
    supplied = dict(overrides or {})
    # Compatibility with earlier callers' alternate key names.
    for old, new in (
        ("button_fg", "button_text"),
        ("selection_bg", "tree_item_selected_bg"),
        ("selection_fg", "tree_item_selected_text"),
    ):
        if old in supplied and new not in supplied:
            supplied[new] = supplied[old]
    palette.update(supplied)
    for alias, base in (
        ("dialog_bg", "widget_bg"),
        ("dialog_input_bg", "editable_value_bg"),
        ("dialog_input_fg", "text_color"),
    ):
        if alias not in supplied:
            palette[alias] = palette[base]
    return palette


def build_qt_palette(app_palette=None) -> QtGui.QPalette:
    """Cover controls rendered by Qt rather than QSS, including disabled text."""
    colors = resolve_palette(app_palette)
    palette = QtGui.QPalette()
    for role, key in (
        (QtGui.QPalette.ColorRole.Window, "widget_bg"),
        (QtGui.QPalette.ColorRole.Base, "editable_value_bg"),
        (QtGui.QPalette.ColorRole.AlternateBase, "table_alt_row_bg"),
        (QtGui.QPalette.ColorRole.WindowText, "text_color"),
        (QtGui.QPalette.ColorRole.Text, "text_color"),
        (QtGui.QPalette.ColorRole.Button, "button_bg"),
        (QtGui.QPalette.ColorRole.ButtonText, "button_text"),
        (QtGui.QPalette.ColorRole.Highlight, "tree_item_selected_bg"),
        (QtGui.QPalette.ColorRole.HighlightedText, "tree_item_selected_text"),
        (QtGui.QPalette.ColorRole.ToolTipBase, "editable_value_bg"),
        (QtGui.QPalette.ColorRole.ToolTipText, "text_color"),
        (QtGui.QPalette.ColorRole.PlaceholderText, "placeholder_text"),
    ):
        palette.setColor(role, QtGui.QColor(colors[key]))
    for role in (
        QtGui.QPalette.ColorRole.WindowText,
        QtGui.QPalette.ColorRole.Text,
        QtGui.QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            QtGui.QPalette.ColorGroup.Disabled, role, QtGui.QColor(colors["disabled_fg"])
        )
    return palette


def style_popup_dialog(dialog: QtWidgets.QDialog, palette=None) -> QtWidgets.QDialog:
    """Style popup containers and their children independently of the editor."""
    dialog.setObjectName(POPUP_DIALOG_OBJECT_NAME)
    dialog.setPalette(build_qt_palette(palette))
    dialog.setStyleSheet(build_application_stylesheet(palette))
    return dialog


def heading_font(base_font: QtGui.QFont, *, prominent=False) -> QtGui.QFont:
    font = QtGui.QFont(base_font)
    if prominent:
        font.setPointSize(font.pointSize() + 2)
    font.setBold(True)
    return font


def build_application_stylesheet(app_palette=None) -> str:
    """Return shared application styles for transient dialogs."""
    palette = resolve_palette(app_palette)
    dialog_bg = palette["dialog_bg"]
    text_color = palette["text_color"]
    dialog_input_bg = palette["dialog_input_bg"]
    dialog_input_fg = palette["dialog_input_fg"]
    border_color = palette["placeholder_border"]
    button_bg = palette["button_bg"]
    button_fg = palette["button_text"]
    input_bg = palette["editable_value_bg"]

    return f"""
        QDialog#SpriteSagePopupDialog QWidget {{
            background-color: {dialog_bg};
            color: {text_color};
        }}
        QMessageBox, QInputDialog, QDialog#SpriteSagePopupDialog {{
            background-color: {dialog_bg};
            color: {text_color};
        }}
        QMessageBox QLabel,
        QMessageBox QLabel#qt_msgbox_label,
        QMessageBox QLabel#qt_msgbox_informativelabel,
        QInputDialog QLabel,
        QDialog#SpriteSagePopupDialog QLabel {{
            background-color: {dialog_bg};
            color: {text_color};
            border: none;
            padding: 8px 0;
        }}
        QMessageBox QTextEdit {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            selection-background-color: {palette['tree_item_selected_bg']};
            selection-color: {palette['tree_item_selected_text']};
        }}
        QMessageBox QPushButton,
        QInputDialog QPushButton,
        QDialog#SpriteSagePopupDialog QPushButton {{
            background-color: {button_bg};
            color: {button_fg};
            border: 1px solid {border_color};
            border-radius: 3px;
            padding: 5px 12px;
            min-height: 20px;
        }}
        QMessageBox QPushButton:hover,
        QInputDialog QPushButton:hover,
        QDialog#SpriteSagePopupDialog QPushButton:hover {{
            background-color: {palette['button_hover_bg']};
        }}
        QMessageBox QPushButton:pressed,
        QInputDialog QPushButton:pressed,
        QDialog#SpriteSagePopupDialog QPushButton:pressed {{
            background-color: {palette['button_pressed_bg']};
        }}
        QMessageBox QPushButton:disabled,
        QInputDialog QPushButton:disabled,
        QDialog#SpriteSagePopupDialog QPushButton:disabled {{
            background-color: {palette['disabled_bg']};
            color: {palette['disabled_fg']};
            border-color: {palette['disabled_border']};
        }}
        QInputDialog QLineEdit,
        QDialog#SpriteSagePopupDialog QLineEdit,
        QDialog#SpriteSagePopupDialog QPlainTextEdit,
        QDialog#SpriteSagePopupDialog QSpinBox,
        QDialog#SpriteSagePopupDialog QDoubleSpinBox,
        QDialog#SpriteSagePopupDialog QComboBox,
        QDialog#SpriteSagePopupDialog QListWidget,
        QDialog#SpriteSagePopupDialog QTabWidget::pane {{
            background-color: {dialog_input_bg};
            color: {dialog_input_fg};
            border: 1px solid {border_color};
            padding: 4px;
            selection-background-color: {palette['tree_item_selected_bg']};
            selection-color: {palette['tree_item_selected_text']};
        }}
        QDialog#SpriteSagePopupDialog QCheckBox {{
            color: {text_color};
            padding: 4px 0;
        }}
        QDialog#SpriteSagePopupDialog QListWidget::item {{
            padding: 3px;
        }}
        QDialog#SpriteSagePopupDialog QListWidget::item:selected {{
            background-color: {palette['tree_item_selected_bg']};
            color: {palette['tree_item_selected_text']};
        }}
        QDialog#SpriteSagePopupDialog QProgressBar {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 3px;
            text-align: center;
        }}
        QDialog#SpriteSagePopupDialog QProgressBar::chunk {{
            background-color: {palette['tree_item_selected_bg']};
        }}
    """


def build_console_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPlainTextEdit {{
            background-color: {palette['console_bg']};
            color: {palette['text_color']};
            border: 1px solid {palette['placeholder_border']};
            font-family: Consolas, Courier New, monospace; /* Added monospace font */
        }}
    """


def build_save_status_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"color: {palette['text_color']}; padding: 6px;"


def build_plain_text_editor_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPlainTextEdit {{
            background-color: {palette['widget_bg']};
            color: {palette['text_color']};
            border: 1px solid {palette['placeholder_border']};
            font-family: Consolas, Courier New, monospace;
        }}
    """


def build_widget_surface_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"background-color: {palette['widget_bg']};"


def build_action_button_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPushButton {{
            background-color: {palette['button_bg']};
            color: {palette['button_text']};
            border: 1px solid {palette['placeholder_border']};
            padding: 2px;
        }}
        QPushButton:hover {{
            background-color: {palette['button_hover_bg']};
            border: 1px solid {palette['button_hover_border']};
        }}
        QPushButton:pressed {{
            background-color: {palette['button_pressed_bg']};
        }}
    """


def build_remove_image_button_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPushButton {{
            background-color: {palette['danger_bg']};
            color: {palette['tree_item_selected_text']};
            border: 1px solid {palette['danger_bg']};
            border-radius: 11px; /* half of _BUTTON_SIZE for a circular button */
            padding: 1px;
        }}
        QPushButton:hover {{
            background-color: {palette['danger_hover_bg']};
        }}
        QPushButton:pressed {{
            background-color: {palette['danger_pressed_bg']};
        }}
    """


def build_image_loader_stylesheet(app_palette=None, border_style="dashed") -> str:
    palette = resolve_palette(app_palette)
    return f"""
        ImageLoaderWidget {{
            background-color: {palette['image_loader_bg']};
            border: 1px {border_style} {palette['image_loader_border']};
            color: {palette['label_color']};
            min-width: 120px;
            min-height: 120px;
            padding: 5px;
        }}
        ImageLoaderWidget:hover {{
            border: 1px {border_style} {palette['tree_item_selected_text']};
        }}
    """


def build_image_preview_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QLabel {{
            background-color: {palette['image_loader_bg']};
            border: 1px solid {palette['placeholder_border']};
            color: {palette['label_color']};
        }}
    """


def build_image_viewer_stylesheet(app_palette=None, border_style="dashed") -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QLabel {{
            background-color: {palette['widget_bg']};
            color: {palette['placeholder_text']};
            border: 1px {border_style} {palette['placeholder_border']};
        }}
    """


def build_logo_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QWidget {{
            background-color: {palette['placeholder_bg']};
            border: 1px solid {palette['placeholder_border']};
        }}
        QLabel {{
            color: {palette['text_color']};
            border: none; background-color: transparent;
        }}
    """


def build_main_window_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QMainWindow, QStatusBar {{ background-color: {palette['window_bg']}; color: {palette['text_color']}; }}
        QStatusBar QLabel {{ color: {palette['label_color']}; padding: 0 8px; }}
        QStatusBar QPushButton {{ background-color: {palette['button_bg']}; color: {palette['text_color']}; border: 1px solid {palette['placeholder_border']}; padding: 3px 10px; }}
        QStatusBar QPushButton:checked {{ background-color: {palette['tree_item_selected_bg']}; color: {palette['tree_item_selected_text']}; }}
        QMenu {{ background-color: {palette['menu_bg']}; color: {palette['text_color']}; }}
        QMenu::item:selected {{ background-color: {palette['tree_item_selected_bg']}; color: {palette['tree_item_selected_text']}; }}
        QMenuBar {{ background-color: {palette['window_bg']}; color: {palette['text_color']}; }}
        QMenuBar::item:selected {{ background-color: {palette['tree_item_selected_bg']}; }}
    """


def build_splitter_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QSplitter::handle {{
            background-color: {palette['splitter_handle']};
        }}
        QSplitter::handle:horizontal {{
            height: 5px; /* Adjust thickness */
            margin: 0px 2px; /* Optional spacing */
        }}
        QSplitter::handle:vertical {{
            width: 5px;  /* Adjust thickness */
            margin: 2px 0px; /* Optional spacing */
        }}
        QSplitter::handle:pressed {{
            background-color: {QtGui.QColor(palette['splitter_handle']).lighter(120).name()};
        }}
    """


def build_scroll_surface_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"background-color: {palette['widget_bg']}; border: none;"


def build_sage_combo_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QComboBox {{
            background-color: {palette['editable_value_bg']};
            color: {palette['text_color']};
            min-height: 24px;
            padding: 4px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {palette['editable_value_bg']};
            selection-background-color: {palette['tree_item_selected_bg']};
            color: {palette['text_color']};
            padding: 4px;
        }}
    """


def build_sage_button_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPushButton {{ background-color: {palette['button_bg']}; color: {palette['button_text']}; border: 1px solid {palette['placeholder_border']}; padding: 5px; min-height: 18px; }}
        QPushButton:hover {{ background-color: {palette['button_hover_bg']}; border: 1px solid {palette['button_hover_border']}; }}
        QPushButton:pressed {{ background-color: {palette['button_pressed_bg']}; }}
    """


def build_sage_label_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QLabel {{
            color: {palette['label_color']};
            padding-right: 5px;
            padding-top: 5px; /* Align with top of widget */
            margin-top: 2px; /* Add slight margin for better alignment with LineEdit */
        }}
    """


def build_sage_value_stylesheet(app_palette=None, is_locked=False) -> str:
    palette = resolve_palette(app_palette)
    bg_color = palette["locked_value_bg"] if is_locked else palette["editable_value_bg"]
    text_color = palette["text_color"]
    border_color = palette["placeholder_border"]
    font_style = "italic" if is_locked else "normal"
    return f"""
        QLineEdit {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            padding: 4px;
            font-style: {font_style};
            min-height: 18px;
        }}
        QLineEdit:read-only {{
             background-color: {palette['locked_value_bg']};
             font-style: italic;
        }}
        QLineEdit:focus {{
            border: 1px solid {palette['text_color']};
            background-color: {palette.get('editable_value_focus_bg', bg_color)};
        }}
    """


def build_sage_table_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    bg_color = palette["editable_value_bg"]
    text_color = palette["text_color"]
    grid_color = palette["table_grid_color"]
    alt_bg_color = palette["table_alt_row_bg"]
    selection_bg = palette["tree_item_selected_bg"]
    selection_fg = palette["tree_item_selected_text"]
    header_bg = palette["table_header_bg"]
    header_fg = palette["table_header_fg"]
    return f"""
        QTableWidget {{
            background-color: {bg_color};
            color: {text_color};
            gridline-color: {grid_color};
            border: 1px solid {palette['placeholder_border']};
            alternate-background-color: {alt_bg_color};
            outline: 0;
        }}
        QTableWidget::item {{
            padding: 4px;
            border-bottom: 1px solid {grid_color};
            border-right: 1px solid {grid_color};
        }}
         QTableWidget::item:selected {{
            background-color: {selection_bg};
            color: {selection_fg};
        }}
        QHeaderView::section {{
            background-color: {header_bg};
            color: {header_fg};
            padding: 4px;
            border: 1px solid {grid_color};
            font-weight: bold;
        }}
        QTableCornerButton::section {{
            background-color: {header_bg};
            border: 1px solid {grid_color};
        }}
    """


def build_sidebar_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"QWidget {{ background-color: {palette['widget_bg']}; border: none; color: {palette['text_color']}; }}"


def build_sidebar_button_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QPushButton {{
            background-color: {palette['button_bg']};
            color: {palette['button_text']};
            border: 1px solid {palette['placeholder_border']};
            padding: 5px 15px;
            min-height: 25px;
            border-radius: 3px;
        }}
        QPushButton:hover {{
            background-color: {palette['button_hover_bg']};
        }}
        QPushButton:pressed {{
            background-color: {palette['button_pressed_bg']};
        }}
    """


def build_recent_projects_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QListWidget#RecentProjectsList {{
            background-color: {palette['tree_bg']};
            color: {palette['text_color']};
            border: 1px solid {palette['placeholder_border']};
            outline: 0;
        }}
        QListWidget#RecentProjectsList::item {{
            padding: 5px 6px;
        }}
        QListWidget#RecentProjectsList::item:selected {{
            background-color: {palette['tree_item_selected_bg']};
            color: {palette['tree_item_selected_text']};
        }}
        QListWidget#RecentProjectsList::item:hover {{
            background-color: {QtGui.QColor(palette['tree_item_selected_bg']).lighter(115).name()};
        }}
    """


def build_tree_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QTreeView {{
            background-color: {palette['tree_bg']};
            color: {palette['text_color']};
            border: none;
            outline: 0;
        }}
        QTreeView::item {{
            padding: 3px 0px;
            color: {palette['text_color']};
            background-color: transparent;
        }}
        QTreeView::item:selected {{
            background-color: {palette['tree_item_selected_bg']};
            color: {palette['tree_item_selected_text']};
        }}
        QTreeView::item:hover {{
            background-color: {QtGui.QColor(palette['tree_item_selected_bg']).lighter(115).name()};
        }}
        QTreeView::branch {{
            background: transparent;
        }}
    """


def build_menu_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QMenu {{
            background-color: {palette['menu_bg']};
            color: {palette['menu_text']};
            border: 1px solid {palette['placeholder_border']};
        }}
        QMenu::item:selected {{
            background-color: {palette['tree_item_selected_bg']};
            color: {palette['tree_item_selected_text']};
        }}
    """


def build_sprite_editor_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    bg_color = palette["widget_bg"]
    text_color = palette["text_color"]
    label_color = palette["label_color"]
    border_color = palette["placeholder_border"]
    button_bg = palette["button_bg"]
    button_fg = palette["button_text"]
    input_bg = palette["editable_value_bg"]
    general_button_padding = "4px 8px"
    move_button_padding = "2px"
    return f"""
        QWidget {{ background-color: {bg_color}; color: {text_color}; }}
        QLabel {{ color: {label_color}; padding-top: 3px; }}
        QTabWidget::pane {{
            border: 1px solid {border_color};
            background-color: {bg_color};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {button_bg};
            color: {button_fg};
            border: 1px solid {border_color};
            border-bottom: none;
            padding: 5px 12px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background-color: {bg_color};
            color: {text_color};
            border-bottom: 1px solid {bg_color};
        }}
        QTabBar::tab:hover {{
            background-color: {palette['tab_hover_bg']};
        }}
        QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            padding: 3px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}
        QGroupBox {{
            color: {label_color};
            border: 1px solid {border_color};
            margin-top: 10px;
            padding-top: 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 3px 0 3px;
            left: 10px;
        }}
        QListWidget {{
            background-color: {input_bg};
            border: 1px solid {border_color};
            alternate-background-color: {palette['list_alt_bg']};
        }}
         QListWidget::item:selected {{
             background-color: {palette['tree_item_selected_bg']};
             color: {palette['tree_item_selected_text']};
         }}
        QPushButton {{
            background-color: {button_bg};
            color: {button_fg};
            border: 1px solid {border_color};
            padding: {general_button_padding};
            min-height: 18px;
        }}
        QPushButton:hover {{ background-color: {palette['button_hover_bg']}; }}
        QPushButton:pressed {{ background-color: {palette['button_pressed_bg']}; }}
        QPushButton:disabled {{ background-color: {palette['disabled_bg']}; color: {palette['disabled_fg']}; border-color: {palette['disabled_border']}; }}
        QPushButton:checked {{ background-color: {palette['tree_item_selected_bg']}; color: {palette['tree_item_selected_text']}; }}
        QPushButton:focus, QComboBox:focus, QSpinBox:focus {{
            border: 1px solid {palette['tree_item_selected_bg']};
        }}
        QMenu {{ background-color: {input_bg}; color: {text_color}; border: 1px solid {border_color}; }}
        QMenu::item {{ padding: 7px 22px; }}
        QMenu::item:selected {{ background-color: {palette['tree_item_selected_bg']}; color: {palette['tree_item_selected_text']}; }}
        QMenu::item:disabled {{ color: {label_color}; }}
        QToolTip {{ background-color: {input_bg}; color: {text_color}; border: 1px solid {border_color}; }}
        QListWidget::item {{ padding: 4px; }}
        QListWidget#FrameTimeline::item {{ border: 2px solid transparent; border-radius: 4px; }}
        QListWidget#FrameTimeline::item:selected {{ border-color: {palette['tree_item_selected_bg']}; }}
        QSplitter::handle {{ background-color: {border_color}; }}
        /* Compact directional controls. */
        QPushButton#MoveUpButton, QPushButton#MoveDownButton {{
             padding: {move_button_padding};
             min-width: 24px; /* Ensure enough space for icon */
        }}
    """


def build_startup_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    window_bg = palette["window_bg"]
    border_color = palette["placeholder_border"]
    text_color = palette["text_color"]
    label_color = palette["label_color"]
    widget_bg = palette["widget_bg"]
    selected_bg = palette["tree_item_selected_bg"]
    return f"""
    QWidget#StartupScreen {{
        background-color: {window_bg};
        border: 1px solid {border_color};
    }}
    QLabel#StartupTitle {{
        color: {palette['tree_item_selected_text']};
        font-size: 22px;
        font-weight: 600;
    }}
    QLabel#StartupSubtitle,
    QLabel#StartupStatus {{
        color: {text_color};
        font-size: 12px;
    }}
    QLabel#StartupSubtitle {{
        color: {label_color};
    }}
    QProgressBar {{
        background-color: {widget_bg};
        border: 1px solid {border_color};
        border-radius: 4px;
    }}
    QProgressBar::chunk {{
        background-color: {selected_bg};
        border-radius: 3px;
    }}
    """


def build_transfer_body_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return f"""
        QScrollArea, QWidget#TransferBody, QWidget#TransferDirections,
        QWidget#TransferAdvanced {{ background: {palette['dialog_bg']}; border: none; }}
        QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {palette['placeholder_border']};
            background: {palette['dialog_input_bg']}; }}
        QCheckBox::indicator:checked {{ background: {palette['tree_item_selected_bg']}; }}
    """


def build_preview_padding_stylesheet(app_palette=None) -> str:
    return "padding: 0;"


def build_review_image_stylesheet(app_palette=None) -> str:
    palette = resolve_palette(app_palette)
    return (
        f"background: {palette['dialog_input_bg']}; "
        f"border: 1px solid {palette['placeholder_border']};"
    )

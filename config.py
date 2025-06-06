"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import sys
from PySide6 import QtGui


def base_dir() -> str:
    """
    Get the absolute path to a bundled resource, whether running
    as a PyInstaller-built EXE or as a plain .py script.
    """
    try:
        # PyInstaller sets this attribute when running in a bundle
        base_path = sys._MEIPASS
    except AttributeError:
        # Not frozen: use the script's directory
        base_path = os.path.abspath(".")

    # Now join with the relative path to your resource
    return base_path


GRAPHICS_DIR = os.path.join(base_dir(), "graphics")

# --- Constants ---
MIN_PANEL_WIDTH = 200
MIN_IMAGE_HEIGHT = 100
MIN_EDITOR_CONSOLE_WIDTH = 50
MIN_EDITOR_CONSOLE_HEIGHT = 30
SAGE_FILE_EXTENSION = ".sage"
SIDEBAR_ICON_SIZE = 12
SIDEBAR_DEPTH_COLORS = [
    QtGui.QColor("#3498db"), QtGui.QColor("#2ecc71"), QtGui.QColor("#f1c40f"),
    QtGui.QColor("#e67e22"), QtGui.QColor("#e74c3c"), QtGui.QColor("#9b59b6"),
    QtGui.QColor("#1abc9c"), QtGui.QColor("#7f8c8d"),
]

# --- Logo Path ---
# Assume this script is in the root directory relative to main.py
LOGO_FILENAME = os.path.join(GRAPHICS_DIR, "logo_large.png")


SETTINGS_FILE_NAME = "./.sagesettings"
DEFAULT_SETTINGS = {
    "OPENAI_API_KEY": "",
    "GOOGLE_AI_STUDIO_API_KEY": "",
    "Selected Inference Provider": "TESTING",
}

APP_PALETTE = {
    # Existing keys
    "window_bg": "#2B2B2B",
    "widget_bg": "#3C3F41",        # Used for general widget background AND editable fields in Sage view
    "text_color": "#BBBBBB",       # Used for general text AND editable field text
    "placeholder_bg": "#3C3F41",
    "placeholder_border": "#555555", # Used for general borders AND field borders
    "console_bg": "#313335",
    "splitter_handle": "#555555",
    "button_bg": "#555555",
    "button_text": "#BBBBBB",
    "tree_bg": "#3C3F41",
    "tree_item_selected_bg": "#5A7E9E",
    "tree_item_selected_text": "#FFFFFF",
    "menu_bg": "#4F5254",           # You might need to apply this in menu_bar.py or via global stylesheet
    "menu_text": "#BBBBBB",         # You might need to apply this in menu_bar.py or via global stylesheet

    # --- New keys for Sage Editor View ---
    # Label color (key part): Slightly dimmer than main text
    "label_color": "#909090",
    # Background for locked value fields: Slightly darker/different shade than editable bg
    "locked_value_bg": "#3C3F41", # Same as general widget bg in this case
    # Background for editable value fields: Slightly different for contrast
    "editable_value_bg": "#313335", # Using console bg color for editable fields
}

# --- Constants for Icon Handling ---
# IMPORTANT: Adjust these paths to where your actual icon files are located!
# Using Qt Resource System (qrc) is recommended for better deployment.
FOLDER_ICON_PATH = os.path.join(GRAPHICS_DIR, "folder.png")
IMAGE_ICON_PATH = os.path.join(GRAPHICS_DIR, "image.png")
SPRITE_ICON_PATH = os.path.join(GRAPHICS_DIR, "sprite.png")
SPRITESHEET_ICON_PATH = os.path.join(GRAPHICS_DIR, "spritesheet.png")
UNKNOWN_ICON_PATH = os.path.join(GRAPHICS_DIR, "unknown.png")
BUSY_GIF_PATH = os.path.join(GRAPHICS_DIR, "wizard.gif")
ACTION_ICON_PATH = os.path.join(GRAPHICS_DIR, "inference.png")
IMAGE_GRID_ITEM_SIZE = 120 # Size for each cell in the image grid

EMPTY_SPRITE_TEMPLATE = {
    "uuid": "",
    "name": "",
    "description": "",
    "width": 256,
    "height": 256,
    "base_image": None,
    "animations": {}
}

EMPTY_SAGE_TEMPLATE = {
    "Project Name": "",
    "version": "1.0",
    "createdAt": "",
    "Project Description": "",
    "Keywords": "",
    "Reference Images": ["", "", "", ""],
}

MAX_UNDO_COUNT = 1000

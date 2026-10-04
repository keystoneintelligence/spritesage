"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import sys
from pathlib import Path
from platformdirs import user_data_path

# Compatibility exports; new GUI code should import directly from theme.
from .theme import (
    MIN_PANEL_WIDTH as MIN_PANEL_WIDTH,
    MIN_IMAGE_HEIGHT as MIN_IMAGE_HEIGHT,
    MIN_EDITOR_CONSOLE_WIDTH as MIN_EDITOR_CONSOLE_WIDTH,
    MIN_EDITOR_CONSOLE_HEIGHT as MIN_EDITOR_CONSOLE_HEIGHT,
    SIDEBAR_ICON_SIZE as SIDEBAR_ICON_SIZE,
    SIDEBAR_DEPTH_COLORS as SIDEBAR_DEPTH_COLORS,
    APP_PALETTE as APP_PALETTE,
    build_application_stylesheet as build_application_stylesheet,
)


def base_dir() -> str:
    """
    Get the absolute path to a bundled resource, whether running
    as a PyInstaller-built EXE or as a plain .py script.
    """
    # PyInstaller sets _MEIPASS when running in a bundle.
    base_path = getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])
    return str(base_path)


GRAPHICS_DIR = os.path.join(base_dir(), "graphics")

# --- Constants ---
SAGE_FILE_EXTENSION = ".sage"
RECENT_PROJECTS_KEY = "Recent Projects"
MAX_RECENT_PROJECTS = 5

# --- Logo Path ---
# Assume this script is in the root directory relative to main.py
LOGO_FILENAME = os.path.join(GRAPHICS_DIR, "logo_large.png")


def settings_file_path() -> str:
    return str(user_data_path("Sprite Sage", appauthor=False) / "preferences.json")


SETTINGS_FILE_NAME = settings_file_path()
TESTING_PROVIDER_ENABLED = os.environ.get(
    "SPRITESAGE_ENABLE_TESTING_PROVIDER", "1"
).strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_SETTINGS = {
    "OPENAI_API_KEY": "",
    "GOOGLE_AI_STUDIO_API_KEY": "",
    "Selected Inference Provider": "TESTING" if TESTING_PROVIDER_ENABLED else "OPENAI",
    RECENT_PROJECTS_KEY: [],
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
IMAGE_GRID_ITEM_SIZE = 120  # Size for each cell in the image grid

EMPTY_SPRITE_TEMPLATE = {
    "uuid": "",
    "name": "",
    "description": "",
    "width": 256,
    "height": 256,
    "base_image": "",
    "include_base_image_in_animations": True,
    "pixel_art": True,
    "animations": {},
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

"""Shared rules for project assets and portable file names."""

import os
from pathlib import Path

_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}


def resolve_asset_path(value: str | None, directory: str, *, required: bool = False) -> str:
    """Resolve stored slash styles against the project, preserving optional empty slots."""
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError("Image paths must be strings.")
    root = os.path.abspath(directory)
    path = os.path.abspath(os.path.join(root, value.replace("\\", "/"))) if value else ""
    if not path or os.path.normcase(path) == os.path.normcase(root):
        if required:
            raise ValueError(
                "Animation frames must specify an image file, not an empty path or directory."
            )
        return ""
    if os.path.isdir(path):
        raise ValueError(f"Expected an image file, but this path is a directory: {path}")
    return path


def stored_asset_path(value: str | None, directory: str, *, required: bool = False) -> str:
    """Store project-relative paths, keeping an absolute path for another Windows drive."""
    path = resolve_asset_path(value, directory, required=required)
    if not path:
        return ""
    try:
        path = os.path.relpath(path, directory)
    except ValueError:
        pass  # Windows cannot express a relative path between drives or shares.
    return path.replace("\\", "/")


def path_is_within(path: str, directory: str) -> bool:
    """Compare whole path components with the platform's case rules."""
    path = os.path.normcase(os.path.abspath(path))
    directory = os.path.normcase(os.path.abspath(directory))
    try:
        return os.path.commonpath([path, directory]) == directory
    except ValueError:
        return False


def remap_path(path: str, old_path: str, new_path: str) -> str:
    if not path or not path_is_within(path, old_path):
        return path
    relative = os.path.relpath(path, old_path)
    return os.path.abspath(new_path if relative == "." else os.path.join(new_path, relative))


def validate_file_name(name: str) -> str:
    """Reject path expressions and names that Windows cannot create reliably."""
    if (
        not name
        or name in {".", ".."}
        or name.endswith((" ", "."))
        or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)
        or name.split(".")[0].upper() in _WINDOWS_DEVICES
    ):
        raise ValueError(
            "Enter a valid file or folder name without path separators or reserved characters."
        )
    return name


def safe_asset_name(value: str, *, fallback: str = "sprite", strip: bool = True) -> str:
    """Convert display names to a single portable filename component."""
    name = "".join(char if char.isalnum() or char in "_-" else "_" for char in value)
    if strip:
        name = name.strip("_")
    name = name or fallback
    if name.upper() in _WINDOWS_DEVICES:
        name += "_"
    return name


def export_directory(project_dir: str, folder_name: str) -> str:
    name = validate_file_name(folder_name)
    root = Path(project_dir).resolve()
    target = root / "exports" / name
    if not target.resolve().is_relative_to(root):
        raise ValueError("The export folder must stay inside the project directory.")
    return str(target)

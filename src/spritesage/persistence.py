"""Atomic writes and a persistent checkpoint from before a session's first edit."""

import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, Signal


class SaveEvents(QObject):
    changed = Signal(str, str)


save_events = SaveEvents()
# A session is the application process, not opening/switching editor tabs.
# A fresh process leaves old checkpoints intact until the first actual edit.
_session_checkpoints: set[str] = set()


def atomic_write(path: str | Path, content: bytes) -> None:
    """Flush a sibling temporary file before replacing the destination atomically."""
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def recovery_path(path: str | Path) -> Path:
    path = Path(path).absolute()
    return path.parent / ".spritesage-recovery" / f"{path.name}.previous"


def damaged_path(path: str | Path) -> Path:
    path = Path(path).absolute()
    return recovery_path(path).parent / f"{path.name}.damaged"


def save_document(path: str | Path, data: dict) -> None:
    """Checkpoint the existing file once, before its first edit this session.

    Later edits, Undo/Redo, and timestamp-only saves preserve that checkpoint.
    Checkpoint failures prevent saving.
    Preferences and credentials must never be passed to this function.
    """
    path = Path(path).absolute()
    save_events.changed.emit(str(path), "Saving…")
    try:
        content = json.dumps(data, indent=4, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if path.exists():
            previous = path.read_bytes()
            # Refuse to overwrite corrupt documents; recovery remains available.
            previous_data = json.loads(previous)
            if not isinstance(previous_data, dict):
                raise ValueError("The existing document is not a JSON object.")
            ignored = {"lastSaved"} if path.suffix.lower() == ".sage" else set()
            if {k: v for k, v in previous_data.items() if k not in ignored} == {
                k: v for k, v in data.items() if k not in ignored
            }:
                save_events.changed.emit(str(path), "Saved")
                return
            session_key = os.path.normcase(os.path.abspath(path))
            if session_key not in _session_checkpoints:
                atomic_write(recovery_path(path), previous)
                _session_checkpoints.add(session_key)
        atomic_write(path, content)
    except (OSError, ValueError, TypeError):
        save_events.changed.emit(str(path), "Save failed — changes are unsaved")
        raise
    save_events.changed.emit(str(path), "Saved")


def restore_document(path: str | Path, *, preserve_damaged: bool = False) -> None:
    """Recover a checkpoint without rotating it. Editors record recovery in Undo.

    Unparseable current files are preserved separately before replacement. The
    editor also requests this for JSON that fails its document schema validation.
    """
    path = Path(path).absolute()
    snapshot = recovery_path(path)
    try:
        content = snapshot.read_bytes()
        if not isinstance(json.loads(content), dict):
            raise ValueError("The recovery snapshot is not a JSON object.")
        previous = path.read_bytes() if path.exists() else None
        if previous is not None:
            try:
                valid_previous = isinstance(json.loads(previous), dict)
            except (ValueError, UnicodeError):
                valid_previous = False
            if preserve_damaged or not valid_previous:
                atomic_write(damaged_path(path), previous)
        atomic_write(path, content)
        # Recovery followed by Undo must not overwrite the recovered checkpoint,
        # even when recovery was the first action after restarting the app.
        _session_checkpoints.add(os.path.normcase(os.path.abspath(path)))
    except (OSError, ValueError, TypeError):
        save_events.changed.emit(str(path), "Recovery failed")
        raise
    save_events.changed.emit(str(path), "Saved")

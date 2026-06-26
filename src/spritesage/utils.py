"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from os import PathLike

from PySide6.QtCore import Qt, QSize, QThread, QEventLoop, QObject, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QHBoxLayout,
    QMessageBox,
    QWidget,
    QProgressBar,
    QVBoxLayout,
)
from PySide6.QtGui import QMovie
from typing import Any, TypeVar, Generic, List, Optional, cast
from copy import deepcopy
from time import monotonic
from PIL import Image
from .config import BUSY_GIF_PATH, MAX_UNDO_COUNT

T = TypeVar("T")


class ProjectFileError(Exception):
    """Custom exception for project file related errors."""

    pass


class BusyIndicator:
    def __init__(self, parent=None, message="Please wait...", gif_path=BUSY_GIF_PATH, icon_size=24):
        self._dlg = QDialog(parent)
        self._dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint)
        self._dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QHBoxLayout(self._dlg)
        layout.setContentsMargins(8, 8, 8, 8)

        self._movie = QMovie(gif_path)
        self._movie.setScaledSize(QSize(icon_size, icon_size))
        gif_label = QLabel()
        gif_label.setMovie(self._movie)
        layout.addWidget(gif_label)

        text_label = QLabel(message)
        layout.addWidget(text_label)

    def show(self):
        self._dlg.show()
        self._movie.start()

    def close(self):
        self._movie.stop()
        self._dlg.close()


class _Worker(QObject):
    _finished = Signal(object)
    _errored = Signal(Exception)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self._finished.emit(result)
        except Exception as e:
            self._errored.emit(e)


def call_with_busy(parent, fn, *args, message="Please wait...", **kwargs):
    """Call fn(*args, **kwargs) off the GUI thread while showing a modal busy GIF."""
    dlg = BusyIndicator(parent, message)
    thread = QThread()
    worker = _Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)

    # Capture result or exception
    result_container = {}

    def on_finished(result):
        result_container["result"] = result
        loop.quit()

    def on_error(exc):
        result_container["error"] = exc
        loop.quit()

    # Wire up signals
    thread.started.connect(worker.run)
    worker._finished.connect(on_finished)
    worker._errored.connect(on_error)
    worker._finished.connect(thread.quit)
    worker._errored.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)

    # Show dialog and start work
    dlg.show()
    thread.start()

    # Run a nested event loop so GUI stays responsive
    loop = QEventLoop()
    loop.exec()

    dlg.close()

    # Make absolutely sure the QThread has stopped before we lose our reference
    thread.quit()  # idempotent if already quitting
    thread.wait()  # block until the thread’s event loop really exits

    if "error" in result_container:
        raise result_container["error"]
    return result_container.get("result")


class _ProgressWorker(QObject):
    _finished = Signal(object)
    _errored = Signal(Exception)
    _progress = Signal(int, int, str)

    def __init__(self, fn, *args, progress_kwarg: str = "progress_callback", **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._progress_kwarg = progress_kwarg

    @Slot()
    def run(self):
        try:

            def report_progress(current: int, total: int, detail: str = ""):
                self._progress.emit(current, total, detail)

            self._kwargs[self._progress_kwarg] = report_progress
            result = self._fn(*self._args, **self._kwargs)
            self._finished.emit(result)
        except Exception as e:
            self._errored.emit(e)


def call_with_progress(
    parent,
    fn,
    *args,
    message: str = "Please wait...",
    progress_label: str = "Processing",
    progress_kwarg: str = "progress_callback",
    progress_unit: str = "frames",
    **kwargs,
):
    """Call fn off the GUI thread while showing frame-count progress."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(progress_label)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    status_label = QLabel(message, dialog)
    status_label.setWordWrap(True)
    status_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    layout.addWidget(status_label)

    progress_bar = QProgressBar(dialog)
    progress_bar.setRange(0, 0)
    progress_bar.setValue(0)
    layout.addWidget(progress_bar)

    thread = QThread()
    worker = _ProgressWorker(fn, *args, progress_kwarg=progress_kwarg, **kwargs)
    worker.moveToThread(thread)

    result_container = {}
    started_at = monotonic()

    def format_duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        minutes, remaining_seconds = divmod(seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{remaining_minutes:02d}:{remaining_seconds:02d}"
        return f"{remaining_minutes:d}:{remaining_seconds:02d}"

    def on_progress(current: int, total: int, detail: str):
        elapsed = monotonic() - started_at
        detail = detail or message
        if total > 0:
            if progress_bar.maximum() != total:
                progress_bar.setRange(0, total)
            if current > 0:
                estimated_total = elapsed * total / current
                eta_text = format_duration(estimated_total - elapsed)
            else:
                eta_text = "calculating..."
            label_text = (
                f"{detail}\n\n"
                f"{current} of {total} {progress_unit} complete\n"
                f"Elapsed: {format_duration(elapsed)} | ETA: {eta_text}"
            )
            status_label.setText(label_text)
            progress_bar.setValue(max(0, min(current, total)))
        else:
            progress_bar.setRange(0, 0)
            status_label.setText(f"{detail}\n\nElapsed: {format_duration(elapsed)}")

    def on_finished(result):
        result_container["result"] = result
        loop.quit()

    def on_error(exc):
        result_container["error"] = exc
        loop.quit()

    thread.started.connect(worker.run)
    worker._progress.connect(on_progress)
    worker._finished.connect(on_finished)
    worker._errored.connect(on_error)
    worker._finished.connect(thread.quit)
    worker._errored.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)

    dialog.show()
    thread.start()

    loop = QEventLoop()
    loop.exec()

    dialog.close()
    thread.quit()
    thread.wait()

    if "error" in result_container:
        raise result_container["error"]
    return result_container.get("result")


def prompt_for_llm_settings(parent: QWidget | None, message: str = "") -> bool:
    """Open LLM settings from the main window when inference configuration is missing."""
    window = parent.window() if parent is not None and hasattr(parent, "window") else None
    app_menu_bar = getattr(window, "app_menu_bar", None)
    if app_menu_bar is not None and hasattr(app_menu_bar, "_open_settings_dialog"):
        app_menu_bar._open_settings_dialog()
        return True

    QMessageBox.warning(
        cast(Any, parent),
        "LLM Settings Required",
        message
        or "Configure an inference provider, API key, and models before using AI generation.",
    )
    return False


def ensure_llm_configured(parent, ai_manager) -> bool:
    """Return False and open settings if the selected inference provider is not configured."""
    from .inference import MissingConfigurationException

    get_client = getattr(ai_manager, "get_client", None)
    if not callable(get_client):
        return True

    try:
        get_client()
        return True
    except MissingConfigurationException as e:
        print(f"AI configuration missing: {e}")
        prompt_for_llm_settings(parent, str(e))
        return False


class UndoRedoManager(Generic[T]):
    def __init__(self):
        self._undo_stack: List[T] = []
        self._redo_stack: List[T] = []

    def save_undo_state(self, state: T) -> None:
        """
        Capture a snapshot for undo. Clears redo history.
        """
        if self._undo_stack and state == self._undo_stack[-1]:
            return

        if len(self._undo_stack) == MAX_UNDO_COUNT:
            self._undo_stack.pop(0)

        self._undo_stack.append(deepcopy(state))
        self._redo_stack.clear()

    def perform_undo(self, current_state: T) -> Optional[T]:
        """
        Push current state onto redo stack, pop & return last undo state.
        Returns None if there's nothing to undo.
        """
        if not self._undo_stack:
            return None
        self._redo_stack.append(deepcopy(current_state))
        return self._undo_stack.pop()

    def perform_redo(self) -> Optional[T]:
        """
        Pop last redo state, push it onto undo stack, and return it.
        Returns None if there's nothing to redo.
        """
        if not self._redo_stack:
            return None
        state = self._redo_stack.pop()
        self._undo_stack.append(deepcopy(state))
        return state

    def clear(self):
        self._undo_stack = []
        self._redo_stack = []


_BACKGROUND_REMOVAL_MODEL = None


def _get_background_removal_model():
    import torch
    from ben2 import BEN_Base

    global _BACKGROUND_REMOVAL_MODEL
    if _BACKGROUND_REMOVAL_MODEL is not None:
        return _BACKGROUND_REMOVAL_MODEL

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BEN_Base.from_pretrained("PramaLLC/BEN2")
    model.to(device).eval()
    _BACKGROUND_REMOVAL_MODEL = model
    return model


def remove_background_image(image: Image.Image) -> Image.Image:
    model = _get_background_removal_model()
    foreground = model.inference(image, refine_foreground=True)
    return cast(Any, foreground).convert("RGBA")


def remove_background_images(images: list[Image.Image]) -> list[Image.Image]:
    if not images:
        return []
    model = _get_background_removal_model()
    foregrounds = cast(list[Any], model.inference(images, refine_foreground=True))
    return [cast(Any, foreground).convert("RGBA") for foreground in foregrounds]


def remove_background(from_fpath: str | PathLike[str], to_fpath: str | PathLike[str]):
    image = Image.open(from_fpath)
    foreground = remove_background_image(image)
    cast(Any, foreground).save(to_fpath)

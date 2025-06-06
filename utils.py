"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from PySide6.QtCore import Qt, QSize, QThread, QEventLoop, QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QLabel, QHBoxLayout
from PySide6.QtGui import QMovie
from typing import TypeVar, Generic, List, Optional
from copy import deepcopy
from ben2 import BEN_Base
from PIL import Image
import torch
from config import BUSY_GIF_PATH, MAX_UNDO_COUNT

T = TypeVar('T')

class ProjectFileError(Exception):
    """Custom exception for project file related errors."""
    pass

class BusyIndicator:
    def __init__(self, parent=None, message="Please wait...", gif_path=BUSY_GIF_PATH, icon_size=24):
        self._dlg = QDialog(parent)
        self._dlg.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint)
        self._dlg.setWindowModality(Qt.ApplicationModal)
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
    _errored  = Signal(Exception)

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
        result_container['result'] = result
        loop.quit()

    def on_error(exc):
        result_container['error'] = exc
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
    thread.quit()    # idempotent if already quitting
    thread.wait()    # block until the thread’s event loop really exits

    if 'error' in result_container:
        raise result_container['error']
    return result_container.get('result')


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


def remove_background(from_fpath: str, to_fpath: str):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = BEN_Base.from_pretrained("PramaLLC/BEN2")
    model.to(device).eval()
    image = Image.open(from_fpath)
    foreground = model.inference(image, refine_foreground=True)
    foreground.save(to_fpath)

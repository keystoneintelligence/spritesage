"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from time import monotonic
from typing import Generic, TypeVar

from .config import MAX_UNDO_COUNT

T = TypeVar("T")


@dataclass(frozen=True)
class UndoRedoState:
    can_undo: bool = False
    can_redo: bool = False
    undo_text: str = ""
    redo_text: str = ""
    undo_count: int = 0
    redo_count: int = 0


@dataclass
class UndoableCommand(Generic[T]):
    label: str
    before: T
    after: T
    merge_key: str | None = None
    created_at: float = field(default_factory=monotonic)
    updated_at: float = field(default_factory=monotonic)

    def undo_state(self) -> T:
        return deepcopy(self.before)

    def redo_state(self) -> T:
        return deepcopy(self.after)

    def can_merge(self, merge_key: str | None, now: float, merge_window_seconds: float) -> bool:
        if not self.merge_key or self.merge_key != merge_key:
            return False
        return now - self.updated_at <= merge_window_seconds

    def merge(self, *, label: str, after: T, now: float) -> None:
        self.label = label
        self.after = deepcopy(after)
        self.updated_at = now


class UndoRedoManager(Generic[T]):
    """Command-style undo/redo history for document snapshots.

    Editors remain responsible for applying returned document states to disk and UI. The history
    owns only immutable mementos of before/after states, which keeps the command stack testable and
    independent of Qt widgets.
    """

    def __init__(
        self,
        max_depth: int = MAX_UNDO_COUNT,
        merge_window_seconds: float = 2.0,
    ):
        if max_depth < 1:
            raise ValueError("Undo history depth must be at least 1.")
        self._max_depth = max_depth
        self._merge_window_seconds = merge_window_seconds
        self._undo_stack: list[UndoableCommand[T]] = []
        self._redo_stack: list[UndoableCommand[T]] = []
        self._current_state: T | None = None
        self._clean_state: T | None = None
        self._pending_legacy_before: T | None = None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def undo_text(self) -> str:
        return self._undo_stack[-1].label if self._undo_stack else ""

    @property
    def redo_text(self) -> str:
        return self._redo_stack[-1].label if self._redo_stack else ""

    def state(self) -> UndoRedoState:
        return UndoRedoState(
            can_undo=self.can_undo,
            can_redo=self.can_redo,
            undo_text=self.undo_text,
            redo_text=self.redo_text,
            undo_count=len(self._undo_stack),
            redo_count=len(self._redo_stack),
        )

    def reset(self, state: T | None = None, *, clean: bool = True) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._pending_legacy_before = None
        self._current_state = deepcopy(state) if state is not None else None
        if clean:
            self._clean_state = deepcopy(state) if state is not None else None

    def clear(self) -> None:
        self.reset()

    def mark_clean(self, state: T | None = None) -> None:
        clean_state = self._current_state if state is None else state
        self._clean_state = deepcopy(clean_state) if clean_state is not None else None

    def is_clean(self, current_state: T | None = None) -> bool:
        state = self._current_state if current_state is None else current_state
        return state == self._clean_state

    def record_change(
        self,
        before: T,
        after: T,
        *,
        label: str = "Edit",
        merge_key: str | None = None,
    ) -> bool:
        self._pending_legacy_before = None
        if before == after:
            self._current_state = deepcopy(after)
            return False

        now = monotonic()
        if self._redo_stack:
            self._redo_stack.clear()

        if merge_key and self._undo_stack:
            last_command = self._undo_stack[-1]
            if last_command.can_merge(merge_key, now, self._merge_window_seconds):
                last_command.merge(label=label, after=after, now=now)
                if last_command.before == last_command.after:
                    self._undo_stack.pop()
                self._current_state = deepcopy(after)
                return True

        if len(self._undo_stack) >= self._max_depth:
            self._undo_stack.pop(0)

        self._undo_stack.append(
            UndoableCommand(
                label=label,
                before=deepcopy(before),
                after=deepcopy(after),
                merge_key=merge_key,
                created_at=now,
                updated_at=now,
            )
        )
        self._current_state = deepcopy(after)
        return True

    def undo(self, current_state: T | None = None) -> T | None:
        if not self._undo_stack:
            return None

        command = self._undo_stack.pop()
        if current_state is not None and current_state != command.after:
            command.after = deepcopy(current_state)

        self._redo_stack.append(command)
        state = command.undo_state()
        self._current_state = deepcopy(state)
        return state

    def redo(self) -> T | None:
        if not self._redo_stack:
            return None

        command = self._redo_stack.pop()
        self._undo_stack.append(command)
        state = command.redo_state()
        self._current_state = deepcopy(state)
        return state

    def save_undo_state(self, state: T) -> None:
        """Compatibility shim for the previous snapshot-only API."""
        self._pending_legacy_before = deepcopy(state)
        if self._current_state is None:
            self._current_state = deepcopy(state)

    def perform_undo(self, current_state: T) -> T | None:
        """Compatibility shim for the previous snapshot-only API."""
        if self._pending_legacy_before is not None:
            self.record_change(
                self._pending_legacy_before,
                current_state,
                label="Edit",
            )
        return self.undo(current_state=current_state)

    def perform_redo(self) -> T | None:
        """Compatibility shim for the previous snapshot-only API."""
        return self.redo()


__all__ = ["UndoRedoManager", "UndoRedoState", "UndoableCommand"]

"""Reviewable, recoverable Godot export transactions."""

import base64
import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .persistence import atomic_write

PENDING = ".spritesage-export-pending.json"
BACKUP = ".spritesage-export-previous.json"


def _snapshot(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _local_path(root: Path, name: str) -> Path:
    path = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Unsafe export recovery path.")
    path.resolve().relative_to(root.resolve())
    return path


def _restore(root: Path, data: dict, *, check_current: bool = False) -> None:
    if data.get("version") != 1 or not isinstance(data.get("before"), dict):
        raise ValueError("Unsupported export recovery record.")
    # Validate the whole record before changing any files.
    entries = [
        (_local_path(root, name), None if value is None else base64.b64decode(value, validate=True))
        for name, value in data["before"].items()
    ]
    if check_current:
        after = data.get("after")
        if not isinstance(after, dict):
            raise ValueError("Export recovery record is missing destination fingerprints.")
        for path, content in entries:
            current = _snapshot(path)
            name = path.relative_to(root).as_posix()
            if current != content and (
                current is None or hashlib.sha256(current).hexdigest() != after.get(name)
            ):
                raise ValueError(
                    "Godot files changed after the export. Recovery needs review to preserve those edits."
                )
    for path, content in entries:
        if content is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, content)


def recover_pending_export(root: Path) -> None:
    """Roll back an interrupted transaction before another export is planned."""
    pending = root / PENDING
    if pending.exists():
        _restore(root, json.loads(pending.read_bytes()), check_current=True)
        pending.unlink()


def restore_previous_export(root: str | Path) -> None:
    """Restore the files changed by the last export, including its manifest."""
    root = Path(root)
    recover_pending_export(root)
    _restore(root, json.loads((root / BACKUP).read_bytes()), check_current=True)
    (root / BACKUP).unlink()


@dataclass
class ExportPlan:
    root: Path
    writes: dict[Path, bytes] = field(default_factory=dict)
    guards: dict[Path, bytes | None] = field(default_factory=dict)
    updates: list[str] = field(default_factory=list)
    creations: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    exported_dirs: list[Path] = field(default_factory=list)

    @property
    def unchanged(self) -> bool:
        return not self.writes

    def merge(self, other: "ExportPlan") -> None:
        if self.writes.keys() & other.writes.keys():
            raise ValueError("Two sprites target the same Godot files.")
        for path in self.guards.keys() & other.guards.keys():
            if self.guards[path] != other.guards[path]:
                raise ValueError("Shared files changed while preparing the export. Export again.")
        self.writes.update(other.writes)
        self.guards.update(other.guards)
        self.updates.extend(other.updates)
        self.creations.extend(other.creations)
        self.conflicts.extend(other.conflicts)
        self.exported_dirs.extend(other.exported_dirs)

    def apply(self, *, allow_conflicts: bool = False) -> list[Path]:
        if self.conflicts and not allow_conflicts:
            raise ValueError("Godot conflicts need explicit confirmation before export.")
        for path, expected in self.guards.items():
            if _snapshot(path) != expected:
                raise ValueError(
                    "Files changed after the export preview. Export again to review them."
                )
        if not self.writes:
            return self.exported_dirs
        self.root.mkdir(parents=True, exist_ok=True)
        if (self.root / PENDING).exists():
            raise ValueError("An interrupted export needs recovery before continuing.")
        before = {}
        for path in self.writes:
            name = path.resolve().relative_to(self.root.resolve()).as_posix()
            _local_path(self.root, name)
            previous = _snapshot(path)
            before[name] = None if previous is None else base64.b64encode(previous).decode("ascii")
        after = {
            path.resolve()
            .relative_to(self.root.resolve())
            .as_posix(): hashlib.sha256(content)
            .hexdigest()
            for path, content in self.writes.items()
        }
        journal = json.dumps({"version": 1, "before": before, "after": after}).encode("utf-8")
        pending = self.root / PENDING
        atomic_write(pending, journal)
        try:
            for path, content in self.writes.items():
                atomic_write(path, content)
            atomic_write(self.root / BACKUP, journal)
        except Exception:
            # Keep the pending record if rollback itself fails; the next attempt
            # recovers before planning. Never advance the manifest on failure.
            _restore(self.root, json.loads(journal), check_current=True)
            pending.unlink()
            raise
        pending.unlink()
        return self.exported_dirs

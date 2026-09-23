import json

import pytest

from spritesage import persistence
from spritesage.persistence import (
    atomic_write,
    damaged_path,
    recovery_path,
    restore_document,
    save_document,
)


def test_atomic_write_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    path.write_bytes(b"original")
    monkeypatch.setattr(
        persistence.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError())
    )
    with pytest.raises(PermissionError):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_flush_failure_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    path.write_bytes(b"original")
    monkeypatch.setattr(
        persistence.os, "fsync", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("suffix", [".sprite", ".sage"])
def test_checkpoint_stays_before_first_edit_through_multiple_saves_and_recovery(tmp_path, suffix):
    path = tmp_path / f"hero{suffix}"
    save_document(path, {"name": "first", "lastSaved": "1"})
    assert not recovery_path(path).exists()
    save_document(path, {"name": "second", "lastSaved": "2"})
    save_document(path, {"name": "second", "lastSaved": "3" if suffix == ".sage" else "2"})
    checkpoint = recovery_path(path).read_bytes()
    timestamp = recovery_path(path).stat().st_mtime_ns
    save_document(path, {"name": "third", "lastSaved": "4"})
    save_document(path, {"name": "fourth", "lastSaved": "5"})
    assert json.loads(recovery_path(path).read_bytes())["name"] == "first"
    restore_document(path)
    assert json.loads(path.read_bytes())["name"] == "first"
    restore_document(path)
    assert json.loads(path.read_bytes())["name"] == "first"
    save_document(path, {"name": "edited after recovery"})
    assert recovery_path(path).read_bytes() == checkpoint
    assert recovery_path(path).stat().st_mtime_ns == timestamp
    assert len(list(recovery_path(path).parent.iterdir())) == 1


def test_next_session_retains_old_checkpoint_until_first_edit(tmp_path, monkeypatch):
    path = tmp_path / "project.sage"
    save_document(path, {"name": "original", "lastSaved": "1"})
    save_document(path, {"name": "end of first session", "lastSaved": "2"})
    monkeypatch.setattr(persistence, "_session_checkpoints", set())
    save_document(path, {"name": "end of first session", "lastSaved": "3"})
    assert json.loads(recovery_path(path).read_bytes())["name"] == "original"
    save_document(path, {"name": "next session edit"})
    save_document(path, {"name": "another edit"})
    assert json.loads(recovery_path(path).read_bytes())["name"] == "end of first session"


def test_recovery_before_first_edit_keeps_checkpoint_on_following_saves(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    save_document(path, {"name": "original"})
    save_document(path, {"name": "edited"})
    monkeypatch.setattr(persistence, "_session_checkpoints", set())
    restore_document(path)
    save_document(path, {"name": "edited"})  # Undo recovery
    save_document(path, {"name": "another edit"})
    assert json.loads(recovery_path(path).read_bytes())["name"] == "original"


def test_snapshot_failure_prevents_overwrite(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    save_document(path, {"name": "first"})
    original = path.read_bytes()
    monkeypatch.setattr(persistence, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        save_document(path, {"name": "second"})
    assert path.read_bytes() == original


def test_corrupt_file_is_not_overwritten_and_can_be_recovered(tmp_path):
    path = tmp_path / "hero.sage"
    save_document(path, {"Project Name": "first"})
    save_document(path, {"Project Name": "second"})
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        save_document(path, {"Project Name": "third"})
    assert path.read_bytes() == b"corrupt"
    restore_document(path)
    assert json.loads(path.read_bytes())["Project Name"] == "first"
    assert json.loads(recovery_path(path).read_bytes())["Project Name"] == "first"
    assert damaged_path(path).read_bytes() == b"corrupt"


def test_damaged_copy_failure_prevents_recovery(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    save_document(path, {"name": "original"})
    save_document(path, {"name": "edited"})
    path.write_bytes(b"broken")
    monkeypatch.setattr(persistence, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        restore_document(path)
    assert path.read_bytes() == b"broken"
    assert json.loads(recovery_path(path).read_bytes())["name"] == "original"


def test_failed_restore_preserves_both_versions(tmp_path, monkeypatch):
    path = tmp_path / "hero.sprite"
    save_document(path, {"name": "first"})
    save_document(path, {"name": "second"})
    monkeypatch.setattr(persistence.os, "replace", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        restore_document(path)
    assert json.loads(path.read_bytes())["name"] == "second"
    assert json.loads(recovery_path(path).read_bytes())["name"] == "first"

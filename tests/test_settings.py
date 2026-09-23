import json

import pytest

from spritesage import settings
from spritesage.settings import SECRET_KEYS, SettingsError, SettingsStore


def test_save_keys_only_to_credentials_and_clear_them(tmp_path, credential_store, capsys):
    path = tmp_path / "preferences.json"
    store = SettingsStore(path)
    data = {SECRET_KEYS[0]: "private-openai", SECRET_KEYS[1]: "private-google", "model": "model-a"}
    store.save(data)
    assert json.loads(path.read_text()) == {"model": "model-a"}
    assert json.loads(credential_store.value) == {k: data[k] for k in SECRET_KEYS}
    assert store.load()[SECRET_KEYS[0]] == "private-openai"
    store.save({**data, SECRET_KEYS[0]: "", SECRET_KEYS[1]: ""})
    assert credential_store.value is None
    assert store.load()[SECRET_KEYS[0]] == ""
    assert "private" not in capsys.readouterr().out
    assert not list(tmp_path.rglob("*.previous"))


def test_migrate_legacy_only_after_secure_save(tmp_path, credential_store):
    legacy = tmp_path / ".sagesettings"
    legacy.write_text(json.dumps({SECRET_KEYS[0]: "secret", "model": "chosen"}))
    path = tmp_path / "app-data" / "preferences.json"
    store = SettingsStore(path, legacy)
    assert store.load()[SECRET_KEYS[0]] == "secret"
    assert store.warnings == []
    assert json.loads(legacy.read_text()) == {"model": "chosen"}
    assert json.loads(path.read_text())["model"] == "chosen"
    assert "secret" not in path.read_text()
    assert json.loads(credential_store.value)[SECRET_KEYS[0]] == "secret"
    assert SettingsStore(path, legacy).load()[SECRET_KEYS[0]] == "secret"


def test_locked_store_preserves_legacy_and_sanitizes_error(tmp_path, monkeypatch, credential_store):
    legacy = tmp_path / ".sagesettings"
    original = json.dumps({SECRET_KEYS[0]: "private-secret", "model": "chosen"})
    legacy.write_text(original)
    path = tmp_path / "preferences.json"
    store = SettingsStore(path, legacy)
    monkeypatch.setattr(
        credential_store,
        "set_password",
        lambda *a: (_ for _ in ()).throw(RuntimeError("private-secret")),
    )
    loaded = store.load()
    assert loaded[SECRET_KEYS[0]] == "private-secret"
    assert store.warnings and "private-secret" not in str(store.warnings)
    assert legacy.read_text() == original
    assert not path.exists()
    with pytest.raises(SettingsError):
        store.save_preferences(loaded)
    assert legacy.read_text() == original


def test_failed_preference_commit_rolls_back_credentials(tmp_path, monkeypatch, credential_store):
    store = SettingsStore(tmp_path / "preferences.json")
    store.save({SECRET_KEYS[0]: "original", "model": "old"})
    before = store.path.read_bytes()
    monkeypatch.setattr(
        settings, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError("private-new"))
    )
    with pytest.raises(SettingsError, match="Could not save preferences"):
        store.save({SECRET_KEYS[0]: "private-new", "model": "new"})
    assert store.path.read_bytes() == before
    assert json.loads(credential_store.value)[SECRET_KEYS[0]] == "original"


def test_recent_projects_save_does_not_touch_unavailable_keys(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "preferences.json")
    monkeypatch.setattr(
        settings, "native_keyring", lambda: (_ for _ in ()).throw(RuntimeError("locked"))
    )
    loaded = store.load()
    assert store.warnings
    store.save_preferences({**loaded, "Recent Projects": []})
    assert all(k not in json.loads(store.path.read_text()) for k in SECRET_KEYS)


def test_existing_native_keys_win_and_legacy_scrub_is_retried(
    tmp_path, credential_store, monkeypatch
):
    path = tmp_path / "preferences.json"
    legacy = tmp_path / ".sagesettings"
    legacy.write_text(json.dumps({SECRET_KEYS[0]: "old"}))
    credential_store.value = json.dumps({SECRET_KEYS[0]: "new"})
    original_write = settings.atomic_write

    def fail_cleanup(destination, content):
        if destination == legacy:
            raise PermissionError()
        original_write(destination, content)

    monkeypatch.setattr(settings, "atomic_write", fail_cleanup)
    store = SettingsStore(path, legacy)
    assert store.load()[SECRET_KEYS[0]] == "new"
    assert store.warnings
    monkeypatch.setattr(settings, "atomic_write", original_write)
    assert SettingsStore(path, legacy).load()[SECRET_KEYS[0]] == "new"
    assert SECRET_KEYS[0] not in json.loads(legacy.read_text())

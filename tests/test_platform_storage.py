"""Portable storage checks; native credential round trips are opt-in for CI."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import platformdirs
import pytest

from spritesage import config, settings

# The regular suite replaces native_keyring to protect the developer's credentials.
native_keyring_factory = settings.native_keyring


@pytest.mark.parametrize(
    ("platform", "module", "class_name"),
    [
        ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
        ("darwin", "keyring.backends.macOS", "Keyring"),
        ("linux", "keyring.backends.SecretService", "Keyring"),
    ],
)
def test_native_backend_selection(platform, module, class_name, monkeypatch):
    backend = object()
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{class_name: lambda: backend}))
    with monkeypatch.context() as context:
        context.setattr(sys, "platform", platform)
        selected = native_keyring_factory()
    assert selected is backend


def test_app_data_location_is_independent_of_launch_directory(tmp_path, monkeypatch):
    # Exercise the real platformdirs backend on each OS in the CI matrix.
    expected = platformdirs.user_data_path("Sprite Sage", appauthor=False) / "preferences.json"
    monkeypatch.chdir(tmp_path)
    actual = Path(config.settings_file_path())
    assert actual == expected
    assert actual.is_absolute()
    assert actual.parent != tmp_path


def test_linux_honors_xdg_data_home(monkeypatch):
    from platformdirs.unix import Unix

    # The Unix backend needs a POSIX absolute path, even when tested on Windows.
    # Resolving the path does not create a directory.
    xdg_data_home = "/tmp/spritesage-xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", xdg_data_home)
    assert Path(Unix("Sprite Sage", appauthor=False).user_data_dir) == (
        Path(xdg_data_home) / "Sprite Sage"
    )


@pytest.mark.skipif(
    os.environ.get("SPRITESAGE_TEST_NATIVE_CREDENTIALS") != "1",
    reason="Requires an unlocked native OS credential store (enabled in storage CI).",
)
def test_native_credential_round_trip():
    # Never touch Sprite Sage's real credential entry, even when run on a developer machine.
    backend = native_keyring_factory()
    service = f"Sprite Sage test {uuid.uuid4()}"
    account = "storage-smoke-test"
    try:
        backend.set_password(service, account, "disposable-test-value")
        assert backend.get_password(service, account) == "disposable-test-value"
        backend.set_password(service, account, "replacement-test-value")
        assert backend.get_password(service, account) == "replacement-test-value"
    finally:
        if backend.get_password(service, account) is not None:
            backend.delete_password(service, account)
    assert backend.get_password(service, account) is None

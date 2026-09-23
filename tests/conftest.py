"""Never read or modify the developer's real credential store in tests."""

import pytest
import sys

from spritesage import settings


@pytest.fixture(autouse=True)
def credential_store(monkeypatch, tmp_path):
    # Keep all settings reads, writes, and legacy migration inside the test directory.
    for name, module in list(sys.modules.items()):
        if name.startswith("spritesage.") and hasattr(module, "SETTINGS_FILE_NAME"):
            monkeypatch.setattr(module, "SETTINGS_FILE_NAME", str(tmp_path / "preferences.json"))
    monkeypatch.setattr(settings, "LEGACY_SETTINGS_FILE_NAME", str(tmp_path / ".sagesettings"))

    class MemoryCredentials:
        value = None

        def get_password(self, service, account):
            assert (service, account) == (settings.SERVICE, settings.ACCOUNT)
            return self.value

        def set_password(self, service, account, value):
            self.value = value

        def delete_password(self, service, account):
            self.value = None

    backend = MemoryCredentials()
    monkeypatch.setattr(settings, "native_keyring", lambda: backend)
    return backend

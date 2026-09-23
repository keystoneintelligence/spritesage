"""Preferences on disk; API keys in the native OS credential store."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from keyring.backend import KeyringBackend

from .config import DEFAULT_SETTINGS, SETTINGS_FILE_NAME, RECENT_PROJECTS_KEY
from .persistence import atomic_write
from .recent_projects import recent_projects_from_settings

SECRET_KEYS = ("OPENAI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY")
SERVICE = "Sprite Sage"
ACCOUNT = "api-keys"
LEGACY_SETTINGS_FILE_NAME = ".sagesettings"


class SettingsError(Exception):
    """Safe user-facing text, never a backend exception containing secrets."""


def native_keyring() -> KeyringBackend:
    # Explicit native backends prevent plaintext plugin fallbacks.
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    from keyring.backends.SecretService import Keyring

    return Keyring()


class SettingsStore:
    def __init__(self, path=None, legacy_path=None):
        self.path = Path(path or SETTINGS_FILE_NAME)
        self.legacy_path = (
            Path(legacy_path)
            if legacy_path is not None
            else (
                Path(LEGACY_SETTINGS_FILE_NAME).absolute()
                if self.path == Path(SETTINGS_FILE_NAME)
                else None
            )
        )
        self.warnings: list[str] = []
        self._legacy_data: dict | None = None
        self._migration_pending = False

    def _read_credentials(self) -> dict:
        try:
            raw = native_keyring().get_password(SERVICE, ACCOUNT)
            values = json.loads(raw) if raw else {}
            if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
                raise ValueError()
            return {k: values[k] for k in SECRET_KEYS if values.get(k)}
        except Exception:
            raise SettingsError(
                "The OS credential store is unavailable or locked. Unlock it and retry. "
                "API keys have not been saved to a file."
            ) from None

    def _write_credentials(self, values: dict) -> None:
        try:
            backend = native_keyring()
            if values:
                # One credential entry avoids partially updating multiple keys.
                backend.set_password(SERVICE, ACCOUNT, json.dumps(values))
            elif backend.get_password(SERVICE, ACCOUNT) is not None:
                backend.delete_password(SERVICE, ACCOUNT)
        except Exception:
            raise SettingsError(
                "Could not update the OS credential store. Unlock it and retry. "
                "API keys have not been saved to a file."
            ) from None

    @staticmethod
    def _preferences(settings: dict) -> dict:
        return {k: v for k, v in settings.items() if k not in SECRET_KEYS}

    def _write_preferences(self, settings: dict) -> None:
        try:
            atomic_write(
                self.path, json.dumps(self._preferences(settings), indent=4).encode("utf-8")
            )
        except (OSError, ValueError, TypeError):
            raise SettingsError(
                "Could not save preferences. Check disk space and permissions."
            ) from None

    def save_preferences(self, settings: dict) -> None:
        """Save recent projects without touching or erasing unavailable credentials."""
        if self._migration_pending:
            raise SettingsError(
                "Settings migration is pending. Unlock the OS credential store and save Preferences."
            )
        self._write_preferences(settings)

    def save(self, settings: dict) -> None:
        previous = self._read_credentials()
        credentials = {k: settings[k] for k in SECRET_KEYS if settings.get(k)}
        if credentials != previous:
            self._write_credentials(credentials)
        try:
            self._write_preferences(settings)
        except SettingsError:
            if credentials != previous:
                self._write_credentials(previous)
            raise
        if self._legacy_data is not None and self.legacy_path:
            try:
                # Scrub only after credentials and preferences are committed. No backup of keys.
                atomic_write(
                    self.legacy_path,
                    json.dumps(self._preferences(self._legacy_data), indent=4).encode("utf-8"),
                )
            except OSError:
                raise SettingsError(
                    "Preferences migrated, but the old .sagesettings file could not be cleared. Check its permissions and retry."
                ) from None
            self._legacy_data = None
        self._migration_pending = False

    def load(self) -> dict:
        self.warnings.clear()
        settings = deepcopy(DEFAULT_SETTINGS)
        data = {}
        readable = True
        try:
            if self.legacy_path and self.legacy_path != self.path and self.legacy_path.is_file():
                legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
                if not isinstance(legacy, dict):
                    raise ValueError()
                if not self.path.exists() or any(k in legacy for k in SECRET_KEYS):
                    self._legacy_data = legacy
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
            elif self._legacy_data is not None:
                data = self._legacy_data
            if not isinstance(data, dict):
                raise ValueError()
        except (OSError, ValueError):
            self.warnings.append(
                "Could not read preferences. The original file was left unchanged."
            )
            data = {}
            readable = False
        self._migration_pending = self._legacy_data is not None or any(
            k in data for k in SECRET_KEYS
        )
        settings.update(data)
        settings[RECENT_PROJECTS_KEY] = recent_projects_from_settings(settings)
        try:
            credentials = self._read_credentials()
            # Stored keys win over stale legacy copies; preserve un-migrated keys on retry.
            for key in SECRET_KEYS:
                settings[key] = (
                    credentials.get(key) or data.get(key) or (self._legacy_data or {}).get(key, "")
                )
            if readable and self._migration_pending:
                self.save(settings)
        except SettingsError as error:
            self.warnings.append(str(error))
        if readable and not self.path.exists() and not self._migration_pending:
            try:
                self.save_preferences(settings)
            except SettingsError as error:
                self.warnings.append(str(error))
        return settings

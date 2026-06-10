import pytest

import inference
import utils


def test_ensure_llm_configured_opens_settings_on_missing_config(monkeypatch):
    class DummyManager:
        def get_client(self):
            raise inference.MissingConfigurationException("missing config")

    calls = []
    monkeypatch.setattr(utils, "prompt_for_llm_settings", lambda parent, message: calls.append(message) or True)

    assert utils.ensure_llm_configured(None, DummyManager()) is False
    assert calls == ["missing config"]


def test_ensure_llm_configured_does_not_swallow_other_errors():
    class DummyManager:
        def get_client(self):
            raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        utils.ensure_llm_configured(None, DummyManager())


def test_ensure_llm_configured_accepts_configured_manager():
    class DummyManager:
        def get_client(self):
            return object()

    assert utils.ensure_llm_configured(None, DummyManager()) is True

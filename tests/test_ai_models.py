from spritesage import ai_models


def test_discover_openai_model_options(monkeypatch):
    class DummyModel:
        def __init__(self, model_id):
            self.id = model_id

    class DummyModels:
        def list(self):
            return type("Response", (), {"data": [
                DummyModel("gpt-5.4-mini"),
                DummyModel("gpt-image-1"),
                DummyModel("text-embedding-3-large"),
            ]})()

    class DummyOpenAI:
        def __init__(self, api_key=None):
            assert api_key == "key"
            self.models = DummyModels()

    monkeypatch.setattr(ai_models.openai, "OpenAI", DummyOpenAI)
    options = ai_models.discover_openai_model_options("key")
    by_id = {option.model_id: option for option in options}

    assert by_id["gpt-5.4-mini"].capabilities == ("text",)
    assert by_id["gpt-image-1"].capabilities == ("image",)
    assert "text-embedding-3-large" not in by_id


def test_discover_google_model_options(monkeypatch):
    class DummyModel:
        def __init__(self, name, base_model_id, display_name, supported_generation_methods):
            self.name = name
            self.base_model_id = base_model_id
            self.display_name = display_name
            self.supported_generation_methods = supported_generation_methods
            self.description = ""

    class DummyModels:
        def list(self, config=None):
            assert config == {"page_size": 200, "query_base": True}
            return [
                DummyModel("models/gemini-3.5-flash", "gemini-3.5-flash", "Gemini 3.5 Flash", ["generateContent"]),
                DummyModel("models/gemini-3.1-flash-image", "gemini-3.1-flash-image", "Gemini 3.1 Flash Image", ["generateContent"]),
                DummyModel("models/text-embedding-004", "text-embedding-004", "Embedding", ["embedContent"]),
            ]

    class DummyGClient:
        def __init__(self, api_key=None):
            assert api_key == "key"
            self.models = DummyModels()

    monkeypatch.setattr(ai_models.genai, "Client", DummyGClient)
    options = ai_models.discover_google_model_options("key")
    by_id = {option.model_id: option for option in options}

    assert by_id["gemini-3.5-flash"].capabilities == ("text",)
    assert by_id["gemini-3.1-flash-image"].capabilities == ("image",)
    assert "text-embedding-004" not in by_id


def test_discover_model_options_routes_by_provider(monkeypatch):
    monkeypatch.setattr(ai_models, "discover_openai_model_options", lambda api_key: ["openai"])
    monkeypatch.setattr(ai_models, "discover_google_model_options", lambda api_key: ["google"])

    assert ai_models.discover_model_options(ai_models.PROVIDER_OPENAI, "key") == ["openai"]
    assert ai_models.discover_model_options(ai_models.PROVIDER_GOOGLEAI, "key") == ["google"]
    assert ai_models.discover_model_options("TESTING", "key") == []


def test_refresh_model_cache_for_settings(monkeypatch):
    calls = []

    def fake_refresh(provider, api_key):
        calls.append((provider, api_key))
        return []

    monkeypatch.setattr(ai_models, "refresh_model_cache", fake_refresh)
    errors = ai_models.refresh_model_cache_for_settings({
        "OPENAI_API_KEY": "openai-key",
        "GOOGLE_AI_STUDIO_API_KEY": "",
    })

    assert errors == {}
    assert calls == [(ai_models.PROVIDER_OPENAI, "openai-key")]

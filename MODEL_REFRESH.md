# Model Refresh Runbook

Sprite Sage discovers selectable AI models from each provider account. The app
does not show or use hardcoded real-provider model defaults.

## Runtime Behavior

- `.sagesettings` starts with API keys and the selected provider only.
- At app startup, Sprite Sage attempts provider model discovery once for any
  provider that already has an API key in settings.
- `Settings -> LLM Settings` shows model dropdowns disabled until that provider
  has discovered compatible text and image models.
- OpenAI and Google provider radio buttons are disabled independently until that
  provider has discovered compatible text and image models.
- Each provider has its own refresh button beside its API key.
- Manual refresh with no API key, a provider error, or no compatible models shows
  a popup.
- Inference fails fast for real providers unless the selected provider has an API
  key plus explicit text and image model IDs in `.sagesettings`.
- `TESTING` remains available without API keys or model IDs only when
  `SPRITESAGE_ENABLE_TESTING_PROVIDER` is not set to `0`, `false`, `no`, or
  `off`. Production builds should disable it with that environment flag.
- If an inference action is requested while the selected real provider is missing
  configuration, the editor opens `Settings -> LLM Settings` before attempting
  generation. Provider/API errors after configuration is present still surface as
  normal AI error popups with the provider error message.

## Compatibility

The provider model-list APIs do not always expose exact output modalities.
`ai_models.infer_model_capabilities()` applies conservative ID heuristics to sort
discovered models into the text or image dropdowns. If a provider changes naming
conventions, update that function and add focused tests in `tests/test_ai_models.py`.

## Refresh Checklist

1. Check official provider docs before changing discovery or capability logic:
   - OpenAI models: https://developers.openai.com/api/docs/models
   - OpenAI model list API: https://developers.openai.com/api/reference/resources/models/methods/list
   - OpenAI image generation: https://developers.openai.com/api/docs/guides/image-generation
   - Google Gemini models: https://ai.google.dev/gemini-api/docs/models
   - Google model list API: https://ai.google.dev/api/models
   - Google image generation: https://ai.google.dev/gemini-api/docs/image-generation
2. Update `ai_models.py` when provider discovery shape or model naming changes.
3. If a provider changes request or response shapes, update the provider client in
   `inference.py` and add focused tests in `tests/test_inference.py`.
4. Keep `.sagesettings` out of source control. It stores local API keys and model
   selections.
5. Run verification:

```bash
python -m py_compile ai_models.py config.py inference.py menu_bar.py main_window.py
python -m pytest -q -o filterwarnings= -o addopts=
```

The `-o` options are only needed in lightweight environments missing the optional
pytest coverage and xdist plugins configured by `pytest.ini`.

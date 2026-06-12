# Model Discovery

Sprite Sage discovers real-provider models from the user's own provider account.
It should not present hardcoded OpenAI or Google model IDs as selectable defaults.

## Behavior

- App startup refreshes model discovery once for providers with saved API keys.
- The settings dialog keeps provider model controls disabled until compatible
  text and image models have been discovered for that provider.
- OpenAI and Google can become available independently.
- Real-provider inference requires an API key plus selected text and image model
  IDs. Missing local configuration opens LLM settings before generation starts.
- Provider/API failures after configuration is present are shown as normal AI
  errors.
- `TESTING` is available only when `SPRITESAGE_ENABLE_TESTING_PROVIDER` is not
  set to `0`, `false`, `no`, or `off`.

## Maintenance

- Model discovery and capability filtering live in `ai_models.py`.
- Provider generation/editing calls live in `inference.py`.
- Settings UI availability rules live in `menu_bar.py`.
- If provider model naming changes, update
  `ai_models.infer_model_capabilities()` and `tests/test_ai_models.py`.
- If provider request/response shapes change, update `inference.py` and
  `tests/test_inference.py`.

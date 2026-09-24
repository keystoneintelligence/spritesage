# Model Manager release dependency

`keystone_model_manager-0.3.0-py3-none-any.whl` is built from the sibling
`modelmanager` repository. This initial source snapshot has not been committed
yet; `modelmanager-source.sha256.txt` identifies every authored source file.
The wheel contains the lightweight manager, pinned manifests, and prompt
instructions (about 87 KiB). It does not contain ComfyUI, llama.cpp, Python,
GPU libraries, or model weights.

Wheel SHA-256:
`73e278f7aed5e13511cf3f1b746a0cd02d2dff3787fee8be2f3e2e56bd113a6a`

Install Sprite Sage with `pip install --find-links vendor/wheels -e ".[dev]"`.
See `docs/local-generation.md` for rebuilding and versioning the dependency.
Model Manager uses the same GPL v3 license as Sprite Sage; downloaded engines,
dependencies, and model weights retain their own upstream licenses.

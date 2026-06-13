# Contributing to Sprite Sage

We welcome bug reports, feature ideas, patches, and documentation updates. By
submitting changes, you agree to license your contributions under GPL v3.

## Development

Use Python 3.10. The current Torch/Torchvision pins target Python 3.10, and CI
builds with Python 3.10.

Install the app and developer tooling from `pyproject.toml`:

```bash
python -m pip install -e ".[dev]"
```

Before opening a change, run:

```bash
python -m pytest
python -m ruff check src tests
```

Black and Pyright are installed with `.[dev]`, but they are not required gates
yet. `python -m black --check src tests` and `python -m pyright` currently report
pre-existing formatting/type issues and should be treated as cleanup tools until
those issues are fixed.

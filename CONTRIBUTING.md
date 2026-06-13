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
python -m black --check src tests
python -m ruff check src tests
```

Pyright is installed with `.[dev]`, but it is not a required gate yet.
`python -m pyright` currently reports pre-existing type issues and should be
treated as a cleanup tool until those issues are fixed.

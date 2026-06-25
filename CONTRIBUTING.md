# Contributing to Sprite Sage

We welcome bug reports, feature ideas, patches, and documentation updates. By
submitting changes, you agree to license your contributions under GPL v3.

## Development

Use Python 3.10. The current Torch/Torchvision pins target Python 3.10, and CI
builds with Python 3.10.

Install the app and developer tooling from `pyproject.toml`:

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Before opening a change, run:

```powershell
venv\Scripts\python.exe -m pytest
venv\Scripts\python.exe -m black --check src tests
venv\Scripts\python.exe -m ruff check src tests
```

Pyright is installed with `.[dev]`, but it is not a required project-wide gate
yet. Use focused Pyright checks for new or substantially changed modules, and
avoid increasing the existing typing baseline.

When adding dynamically imported modules or new runtime dependencies, update
the project metadata and packaging configuration as needed.

See [BUILD.md](BUILD.md) for executable packaging instructions.

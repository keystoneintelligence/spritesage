# BUILD INSTRUCTIONS

These steps will build Sprite Sage from source on a clean system.

## Requirements
- Python 3.10
- `pip`, `venv`
- Windows, macOS, or Linux

Sprite Sage currently pins Torch/Torchvision versions that target Python 3.10.
Use Python 3.10 for local development and release builds.

## Steps

```bash
# [Optional] Clean previous builds
rmdir /s /q build dist

# Create a virtual environment
python -m venv venv

# Activate the environment
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS/Linux

# Install dependencies
python -m pip install -e ".[dev]"

# Build the executable
python -m PyInstaller main.spec
```

The output executable appears in the dist/ folder.
Run the build command from the activated virtual environment so PyInstaller uses
the pinned project dependencies, not packages from a global Python install.

## Run Tests

```bash
python -m pytest
```

## Developer Checks

The verified required checks are:

```bash
python -m black --check src tests
python -m ruff check src tests
```

Pyright is installed with `.[dev]`, but it is not a required gate yet.
`python -m pyright` currently reports pre-existing type issues and should be
treated as a cleanup tool until those issues are fixed.

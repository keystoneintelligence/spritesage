# Build Instructions

These steps build Sprite Sage from source and produce the desktop executable.

## Requirements

- Python 3.10
- `pip` and `venv`
- Windows, macOS, or Linux for source development
- Windows for the currently verified `.exe` release build

Runtime dependencies are declared in `pyproject.toml` and installed with the
project. This includes the libraries used by the image, AI, and 3D rendering
features.

Sprite Sage pins Torch/Torchvision versions that target Python 3.10. Release
builds must use the project virtual environment and the CPU-only Torch 1.13.1
build.

## Setup

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run From Source

```powershell
venv\Scripts\spritesage.exe
```

## Build The Executable

Close any running copy of `dist\spritesage.exe` before rebuilding.

```powershell
# Optional clean build
rmdir /s /q build dist

venv\Scripts\python.exe -m PyInstaller --clean main.spec
```

The executable is written to `dist\spritesage.exe`.

The release spec verifies that it is running from a virtual environment with
the pinned CPU-only Torch build. It also collects modules that are loaded
dynamically at runtime.

## Tests

```powershell
venv\Scripts\python.exe -m pytest
```

## Developer Checks

```powershell
venv\Scripts\python.exe -m black --check src tests
venv\Scripts\python.exe -m ruff check src tests
```

Pyright is installed with `.[dev]`, but it is not yet a required project-wide
gate because the repository has a pre-existing typing baseline. Use focused
Pyright checks for new or substantially changed modules.

## Troubleshooting

### `Access is denied: dist\spritesage.exe`

Close the running executable and rebuild.

### Missing runtime dependency

Refresh the environment from the project metadata:

```powershell
venv\Scripts\python.exe -m pip install -e ".[dev]"
```

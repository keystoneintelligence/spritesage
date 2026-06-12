# BUILD INSTRUCTIONS

These steps will build Sprite Sage from source on a clean system.

## Requirements
- Python 3.10+
- `pip`, `venv`
- Windows, macOS, or Linux

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
python -m pip install -r requirements.txt

# Build the executable
python -m PyInstaller main.spec
```

The output executable appears in the dist/ folder.

## Run Tests

```bash
pip install -r requirements.txt -r test_requirements.txt
python -m pytest
```

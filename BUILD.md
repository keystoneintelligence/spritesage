# BUILD INSTRUCTIONS

These steps will build Sprite Sage from source on a clean system.

## Requirements
- Python 3.10+
- `pip`, `venv`
- Windows, macOS, or Linux
- [Optional] PyInstaller (`pip install pyinstaller` if not installed)

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
pip install -r requirements.txt

# Build the executable
pyinstaller main.spec

The output executable appears in the dist/ folder.

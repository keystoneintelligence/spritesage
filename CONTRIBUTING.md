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

## GUI theme

`src/spritesage/theme.py` owns GUI colors, Qt palette roles, typography, size
constants, and stylesheet builders. Add semantic color keys to `APP_PALETTE` in
that file, and use its builders in widgets rather than embedding QSS or color
literals. Widget layout and behavior stay in their own modules.

Use `style_popup_dialog(dialog, palette)` for custom dialogs and message boxes.
It applies both a Qt palette and shared popup styles, including child containers,
so dialogs opened by an editor do not inherit different backgrounds. Ordinary
form labels use the shared dark popup background.

Use `resolve_palette` for custom painting and partial palette overrides. Button
text and selection colors use the canonical `button_text`,
`tree_item_selected_bg`, and `tree_item_selected_text` keys. The old alternate
names are accepted only when resolving overrides. Theme exports from `config`
and `utils` remain compatibility aliases; new UI code should import from `theme`.

`tests/test_theme.py` checks theme ownership and rendered Add Animation colors
against another popup, with both default and custom palettes.

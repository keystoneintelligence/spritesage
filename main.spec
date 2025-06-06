# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

# 1. Gather all submodule NAMES under google.genai (e.g. "google.genai.client", etc.)
google_genai_submodules = collect_submodules('google.genai')

# 2. Gather all actual file paths under site-packages/google/genai/
#    Each tuple in this list is (source_path, destination_relative_path_in_EXE).
google_genai_data = collect_data_files('google.genai', include_py_files=True)

safetensors_datas, safetensors_binaries, safetensors_hiddenimports = collect_all('safetensors')

a = Analysis(
    ['main.py'],
    pathex=[r"F:\data\keystoneintelligence\spritesage"],
    binaries=safetensors_binaries,
    datas=[
        ('graphics', 'graphics'),
    ] + safetensors_datas + google_genai_data,
    hiddenimports=(
        google_genai_submodules + safetensors_hiddenimports + ['numpy.core._multiarray_umath']
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='spritesage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='graphics/wizard.gif',
)

# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

ROOT = Path.cwd()
SRC_DIR = ROOT / "src"

if sys.prefix == sys.base_prefix:
    raise RuntimeError(
        "Release builds must run from the project virtual environment. "
        "Use .\\venv\\Scripts\\python.exe -m PyInstaller main.spec"
    )

import torch

if torch.version.cuda is not None:
    raise RuntimeError(
        f"Refusing to bundle CUDA-enabled Torch {torch.__version__}. "
        "Install the pinned CPU-only release dependencies."
    )
if torch.__version__.split("+", 1)[0] != "1.13.1":
    raise RuntimeError(
        f"Expected Torch 1.13.1 for the release build, found {torch.__version__}."
    )

def is_google_genai_runtime_module(name):
    return (
        '.tests' not in name
        and not name.endswith('._test_api_client')
    )


google_genai_submodules = collect_submodules(
    'google.genai',
    filter=is_google_genai_runtime_module,
)
google_genai_data = collect_data_files(
    'google.genai',
    excludes=['tests/**'],
)

safetensors_datas, safetensors_binaries, safetensors_hiddenimports = collect_all('safetensors')
model_baker_submodules = collect_submodules('spritesage.model_baker')
pygltflib_submodules = collect_submodules('pygltflib')

a = Analysis(
    ['src/spritesage/main.py'],
    pathex=[str(SRC_DIR)],
    binaries=safetensors_binaries,
    datas=[
        ('graphics', 'graphics'),
    ] + safetensors_datas + google_genai_data,
    hiddenimports=(
        google_genai_submodules
        + safetensors_hiddenimports
        + model_baker_submodules
        + pygltflib_submodules
        + ['numpy.core._multiarray_umath']
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython',
        'astropy',
        'diffusers',
        'gradio',
        'jupyter',
        'matplotlib',
        'numba',
        'pandas',
        'pyarrow',
        'pytest',
        'scipy',
        'transformers',
    ],
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

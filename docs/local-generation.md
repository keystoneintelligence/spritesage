# Local generation integration

Sprite Sage depends on `keystone-model-manager==0.3.0`. The release wheel is
vendored in `vendor/wheels` so a source checkout can be installed before the
package is published to a registry. Its source lives in the sibling
`modelmanager` repository. Sprite Sage's `local_inference.py` only translates
the existing image requests and delegates to the package.

The package owns the curated catalog, model checksums, pinned ComfyUI runtime,
isolated Python setup, cache discovery, download/resume, worker processes,
Qwen workflows, and optional Qt setup/progress dialogs. It has no Sprite Sage
imports. The host supplies a palette and persists the returned configuration;
MeshHub can eventually use the core without adopting the Qt interface.

## Packaging

From Sprite Sage's root, rebuild the wheel after changing Model Manager:

```powershell
venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation ..\modelmanager -w vendor/wheels
venv\Scripts\python.exe -m pip install --no-deps --force-reinstall vendor/wheels/keystone_model_manager-0.3.0-py3-none-any.whl
venv\Scripts\python.exe -m PyInstaller --clean --noconfirm main.spec
```

Bump the package version and Sprite Sage pin together for subsequent releases.
Commit the matching wheel and its source revision/hash in `vendor/wheels/README.md`.
The release includes package code and runtime manifests, not ComfyUI, its Python,
GPU dependencies, or model weights. Sprite Sage's CPU Torch remains separate
from the local engine's CUDA Torch.

## Configuration and ownership

The catalog is the starting point. Each model has its own Install/Resume/Verify/
Use action and status. Installation provisions only the selected model and any
missing compatible runtime. It never installs other catalog entries. Only Use
changes the host application's selected model; downloaded models remain available
for later switching. Advanced settings and maintenance actions are collapsed or
in a model menu. Technical installation output is under Show details.

`library.json` in the selected state directory stores independent model settings
and verified engine connections. It does not contain the host's active provider
or change that provider. Model license acknowledgments and generation defaults
are kept separate; changing a model revision invalidates its library verification.
The existing `LOCAL_GENERATION` configuration is supported without migration.

Each catalog profile declares its runtime family, workflow, capabilities, and
generation defaults. New model families require a tested workflow registration
in Model Manager; unsupported workflows/runtimes are rejected before downloads.
The current catalog still contains Qwen Image 2.1 only. Multi-model installation,
selection, and persistence are tested with additional fixture profiles.

`LOCAL_GENERATION` is a JSON object in the existing preferences file. Paths come
from the user's selections or platform application-data defaults. Runtime,
model storage, Python executable, and state directories are configurable. No
developer-machine paths are shipped. Changing generation settings does not
change cloud provider settings.

Managed model folders use `<model-id>/<pinned-revision>`. All required files
must match their exact sizes and SHA-256 hashes before a verification receipt
is written. A changed path, size, or modification time invalidates readiness.
Interrupted downloads keep partial bytes and resume; failed checksums are never
published as installed files. Model Manager does not automatically update pins.

Existing ComfyUI model trees and the exact pinned Hugging Face snapshot can be
verified and borrowed. Externally installed files are never deleted or updated.
Managed removal only deletes catalog files and partial downloads in an owned
revision directory, leaving unrelated files intact. Downloads and inference
hold cache locks to prevent managed removal while a model is in use. Apps
outside Model Manager do not participate in these locks.

Generation launches a private loopback-only ComfyUI process with separate
input/output/state directories. Custom/API nodes are disabled. The process
stops after generation or cancellation, releasing GPU memory. Existing running
ComfyUI sessions are not stopped or reused; close GPU-intensive sessions if
memory is tight. Cancellation preserves partial installations for retry.

## Diagnostics and current scope

`dist\spritesage.exe --check-local-generation` verifies the configured model
files, starts the selected runtime, checks required nodes and model visibility,
then shuts down. It exits nonzero with an actionable error if setup fails.
Engine diagnostics live in `<state_root>/logs/last-engine.log`; managed install
diagnostics live in `<runtime_root>/setup.log`.

The initial automatic runtime targets Windows x64/NVIDIA (CUDA 12.6, Torch 2.9).
It was exercised on a GTX 1070 with compatibility settings and CPU text/VAE
offload. CPU mode is explicit and very slow. Other GPU backends and operating
systems do not yet have a tested automatic installer. Existing-runtime mode
requires compatible ComfyUI nodes and Python dependencies; verification reports
incompatible installations without modifying them.

Qwen is an image model, not a local text assistant. Cloud text assistance is
explicit and off by default. The Qwen model license is shown before installation
or connection; this first curated model is limited to research/evaluation
without a separate commercial license.

## Qwen prompt enhancement

Qwen's default installation now includes both local prompt helpers and the editing
vision adapter (27.44 GiB total weights), plus missing ComfyUI and portable
llama.cpp engines. The catalog displays download size and installation space.
Only the selected catalog model and its declared dependencies are installed.

The manager chooses PE-T2I for requests without references and PE-I2I otherwise.
It releases the helper process before loading ComfyUI. Sprite Sage passes its
background, framing, camera, and animation constraints through the package's
`generation.generate_image` facade. Existing cloud workflows are unchanged.

Old configurations retain image-only behavior until Add prompt enhancement is
chosen. Existing Studio helper files are discovered relative to the selected
installation and borrowed after verification. Advanced includes the automatic
prompt improvement toggle and optional helper model/engine folder overrides.
No machine-specific paths are built into either package. Removing an image model
retains shared prompt components and engines; external files are never removed.

A failed helper offers Retry, Generate with original prompt, or Cancel. The
original-prompt choice applies to that request only. Cancellation stops the job.
The specialized helpers do not replace description/keyword/animation-name tools.

For release validation, `spritesage.exe --test-local-generation request.json`
executes the editor's actual adapters. The JSON contains `operation` (`base`,
`reference`, `next`, or `between`), an `input` object matching its inference
dataclass, and optionally a `config` object for isolated test state. Without
`config`, saved local settings are used. It prints the output path and exits
nonzero on failure. This command performs generation and is only run explicitly.

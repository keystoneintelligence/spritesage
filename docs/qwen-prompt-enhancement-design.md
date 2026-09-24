# Qwen prompt enhancement integration

Investigation: 2026-09-24. Implemented in Model Manager 0.3.0. The findings below
record the pre-change state and the design used for implementation. Shared prompt
components are retained on image-model removal; automatic garbage collection is
not included. See local-generation.md for the current integration.

## Recommendation

Keep one user-facing Qwen Image 2.1 catalog entry. Its installation recipe should
include its image weights, both prompt enhancers, the editing vision projector,
and compatible ComfyUI and llama.cpp engines. Install only missing components
of the selected recipe. Other catalog models remain independent choices.

Model Manager owns component downloads, verification, discovery, process
lifecycle, and workflow execution. Sprite Sage supplies the image request and
its constraints. This extends the existing package boundary without making
Sprite Sage aware of individual GGUF files or engine command lines.

## Findings from the installed Studio

The current implementation is in `work/gguf-editor/prompt_enhancer.py` and
`studio.py` under the existing Local Image Studio workspace. The runtime records
its dependencies in `prompt-enhancement/gguf/manifest.json` and its upstream
prompt source in `prompt-enhancement/source.json`.

| Component | Installed format | Purpose | Bytes |
| --- | --- | --- | ---: |
| Qwen-Image-2.1-PE-T2I | Q4_K_M GGUF | Rewrite requests with no reference images | 5,629,108,864 |
| Qwen-Image-2.1-PE-I2I | Q4_K_M GGUF | Rewrite requests with reference images | 5,629,108,864 |
| I2I vision projector | BF16 GGUF | Supply images to the editing helper | 921,704,608 |

These are separate from the Qwen3-VL text encoder already required by the image
workflow. Qwen's [official documentation](https://github.com/QwenLM/Qwen-Image-2.1#prompt-rewriting)
describes two specialized prompt-rewriting checkpoints, for generation and
editing. The installed GGUF files are community conversions of those checkpoints.

The inspected Studio code:

- Selects T2I without references, or I2I with any references. It does not run both
  helpers for one image.
- Uses llama.cpp release `b11160` with CUDA 12.4, as a portable native runtime.
  It does not require another Python environment for the helper itself.
- Starts a private, authenticated loopback server for each request; passes
  reference images in order; enables full reasoning; validates completion and
  extracts the final rewritten prompt.
- Checks context capacity, including references and the full output allowance
  (16,256 tokens for T2I; 24,000 for I2I). Keeps the vision projector on CPU.
- Adds the requested aspect ratio to the helper input but retains application
  control of image dimensions. Reapplies transparency wording when requested.
- Stops the helper before starting ComfyUI. Enhancement failures stop the job;
  there is no silent fallback.

The Studio README records enhancement times of 97 seconds for generation and
120 seconds for single-reference extraction on the GTX 1070, with total times
of 4m53s and 5m30s respectively at 512 by 512 / 25 steps. These are existing
reported benchmarks, not measurements rerun during this investigation.

Current Sprite Sage calls `modelmanager.comfy.generate_image` directly.
Model Manager 0.2.0 installs only the three core image files and ComfyUI.
Neither currently discovers, verifies, installs, or invokes these helpers.

## User experience

1. Choose **Local**, select **Qwen Image 2.1**, then **Install model**.
2. The model card says **Includes automatic prompt enhancement** and shows the
   missing download size and required free space before installation.
3. One progress view handles setup, downloads, verification, and readiness.
   Component names and technical output remain in **Show details**.
4. **Use model** activates Qwen. Generation shows **Improving prompt**, then
   **Generating image**, with elapsed time and cancellation throughout.

Install both helpers by default as part of this one selected image model, so
switching between creation and editing needs no additional setup or network.
Do not expose the helpers as separate image-model choices.

Under Advanced, provide **Automatically improve prompts**, enabled for new
complete installations. Disabling it skips the helper stage, without uninstalling
files. Keep quantization, engine selection, and GPU fitting as curated defaults.
Custom component locations can be overridden under Advanced for existing setups.

An existing image-only installation remains usable with its current behavior.
Offer **Add prompt enhancement** on its Qwen card; show the missing bytes and
reuse detected, verified components. Enable enhancement after successful setup.
If all helpers already exist, verify and connect them instead of downloading
copies. For an enhanced installation, a missing or changed helper is a repair
condition, not a reason to silently bypass enhancement.

If enhancement fails during generation, preserve the request and offer Retry or
Generate with original prompt. The latter is an explicit user choice and should
not silently change the saved default. Cancellation must never trigger fallback.

The three additional model files total **11.34 GiB (12.18 GB)**. Combined with
the existing image weights, model storage is **27.44 GiB**, before engines and
temporary installation space. The pinned llama.cpp download archives add about
646 MB; their expanded disk footprint must be budgeted separately. Calculate
actual missing bytes and peak free-space requirements by target volume.

## Package design

The current profile assumes one Hugging Face repository/revision and one runtime.
Appending the GGUF files to its existing `files` tuple would download from the
wrong repository and would not provision their engine.

Introduce a small declarative recipe with component dependencies:

```text
Qwen Image 2.1 recipe
  image weights + ComfyUI runtime
  creation prompt weights + llama.cpp runtime
  editing prompt weights + vision projector + same llama.cpp runtime
  pinned system prompts and inference settings
```

Each component needs its own stable identity, source, immutable revision,
file sizes and hashes, runtime requirements, and license metadata. Keep the
existing Qwen catalog ID stable; version the recipe separately. Verification
must include a digest of all recipe dependencies, their resolved locations,
and runtime compatibility, not only the image repository revision.

Preserve resumable downloads and per-component complete-installation receipts.
Only report the enhanced recipe ready once all required components and engines
are verified. Interrupted setup resumes missing work. Distinguish image-only
readiness from complete enhanced readiness in stored state.

Resolve configurable model/runtime roots and explicit borrowed paths first.
Discover known layouts relative to a user-selected installation, including
adjacent `prompt-enhancement/gguf` and `llama.cpp` directories. Do not hardcode
the investigated machine's absolute paths. Treat local manifests as hints;
validate files against trusted catalog pins before using them.

Reuse identical components across recipes. Track managed ownership and users of
shared components so removing one recipe cannot delete another's dependencies.
Borrowed files are never removed or updated. Hold component leases during both
enhancement and image generation; serialize access to the selected GPU within
Model Manager. Unrelated applications remain outside these locks.

Use a package-level image-generation facade to orchestrate:

```text
validate request and component readiness
  -> select helper from reference presence
  -> run helper and validate final output
  -> stop owned helper process and release resources
  -> apply host constraints to the image prompt
  -> run existing ComfyUI workflow
  -> clean up owned processes and temporary inputs
```

Reuse Model Manager's hidden subprocess handling, cancellation, and frozen-app
environment isolation for llama.cpp. Verify its binary/dependency inventory and
perform a startup compatibility probe. Preserve full helper output allowances;
do not silently reduce reasoning to meet a latency target. Resource checks must
use the actual configured locations and detected hardware, rather than copying
the Studio's fixed drive-space guards. Test CPU mode explicitly before claiming
enhanced CPU support; retain image-only compatibility if it cannot be supported.

## Sprite constraints

The inspected T2I system prompt encourages long, detailed scene expansion. A
generic rewrite could introduce scenery or change sprite framing. Pass explicit
host constraints separately from descriptive content, including request purpose,
background policy, camera, style, dimensions, and reference roles/order.

Sprite Sage currently asks for plain white backgrounds for base sprites and
animation frames. Preserve that behavior; do not automatically switch it to
transparency. Keep dimension selection in the application. Treat helper ratio
fields as advisory, and retain both references in the correct order for in-between
frames. Reapply mandatory constraints after rewriting and validate the structured
output, including reference identifiers. Semantic fidelity still requires actual
image QA; schema validation alone cannot guarantee it.

Store only the final usable rewrite in memory as needed for generation or optional
details. Do not present or persist the helper's reasoning transcript. These
specialized helpers do not replace Sprite Sage's separate description, keyword,
or animation-name assistants.

## Observed pins for implementation

| Source | Revision | File | SHA-256 |
| --- | --- | --- | --- |
| `prithivMLmods/Qwen-Image-2.1-PE-T2I-GGUF` | `e18d4a3e0830ab157770738b16830e6fcf5f57d4` | `Qwen-Image-2.1-PE-T2I.Q4_K_M.gguf` | `340feb42c784e35b704a0f0d8d1c679a3fe60437bd9ea44a7a6fd2d730470506` |
| `prithivMLmods/Qwen-Image-2.1-PE-I2I-GGUF` | `55b9c1a326599e142d59bcad8715d5601ccf8daa` | `Qwen-Image-2.1-PE-I2I.Q4_K_M.gguf` | `a5c6cb28cbaf838834d1335c8392619af5809d9fe95d0ebd321e15751866dfe9` |
| Same I2I source | Same revision | `Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf` | `8dedb71dbc3092dc47de9108ad373d68a12854e2527d59bd9399601738f3bce1` |

The local manifest also records both `b11160` runtime archive sizes and hashes.
The upstream system prompts are pinned to `QwenLM/Qwen-Image-2.1` revision
`fb7ae1d1f9611cd91524d03c53c5246b36ac8577`. Carry these assets and their provenance
into the package's trusted catalog, with component-specific license notices.
These pins were read from the local manifests; this investigation did not
re-hash the large files or execute the helper runtime.

## Acceptance checks before release

- Clean machine: one model action provisions the complete recipe; shared
  engines are reused; unrelated catalog models are not installed.
- Existing setups: complete Studio layout, image-only ComfyUI tree, separate
  model/runtime drives, and explicit custom helper paths all behave correctly.
- Integrity: missing projector, changed GGUF, changed system prompt, runtime
  mismatch, interrupted download, and insufficient space cannot report ready.
- Sharing: removing one recipe retains shared and borrowed files; active
  generation prevents removal of leased managed components.
- Requests: no references uses T2I; one or multiple references use I2I in order;
  explicit dimensions, backgrounds, sprite framing, and animation roles survive.
- Lifecycle: errors, cancellation, and malformed/truncated helper output stop
  owned processes; ComfyUI does not start before helper shutdown; fallback is
  explicit and never triggered by cancellation.
- Release: exercise creation, reference generation, next-frame and in-between
  workflows from the frozen executable on the GTX 1070; inspect sprite quality,
  peak RAM/VRAM, and latency before changing defaults for existing installations.

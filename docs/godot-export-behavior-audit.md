# Godot export behavior audit

Compared `e95f479` (the first preservation build) with its main-branch base `d9077d7`, then traced new-export, repeat-export, static, animated, project, cancellation, failure, and recovery paths. This report records both accidental regressions and deliberate contract changes. Corrections are on `codex/godot-export-preservation`, PR #37.

## Regressions corrected

| Behavior | Main / previous workflow | First preservation build | Correction and verification |
| --- | --- | --- | --- |
| Animated background removal | Resize frames and automatically remove backgrounds where meaningful alpha is absent; batch model calls | Passed `extract_alpha=False`, bypassing the pipeline entirely | Restore the same alpha detection and batched cleanup for first exports and only changed frames. Regression checks verify pipeline calls, output alpha, source files unchanged, and siblings untouched. |
| Static background removal | Always call the existing background-removal utility | Copy raw RGBA | Restore the existing model pipeline for first exports and changed static images. No-op exports avoid processing. |
| Replacement-frame sizing | Animated export resizes using NEAREST for pixel art or LANCZOS otherwise | First export resized, but a later replacement with different source dimensions failed | Both first and later exports use the same resize pipeline; existing atlas/canvas dimensions remain stable. |
| Static image sizing | Preserve actual source image dimensions | A replacement with different image dimensions failed | Restore source dimensions for static replacement; the scene stays untouched. Changes to the sprite's declared canvas remain a separate structural restriction. |
| Static output filename | Source image basename, such as `base.png` | Sprite name, such as `Static.png` | Restore source basename on first export. Record that destination in the manifest and keep it on later source renames. First-preview manifests without the new field retain their existing `<asset>.png` destination. |
| Alpha composition | Composite onto a transparent cell; semitransparent alpha applied once | Raw RGBA copy retained hidden RGB under completely transparent pixels | Restore legacy cell composition on first and changed-frame exports. A test checks semitransparent alpha remains 128, rather than being applied twice. |
| Destination dialog | Folder name remained editable on each export | A remembered direct folder disabled the name field with no return to normal mode | Add “Use project exports folder,” restoring editable folder names and clearing the remembered custom destination after success. |
| Scene binding validation | Regeneration made the scene reference the generated asset | Preserved any scene bytes, even after a user rebound it to another resource; could update an unused file and report success | Verify the scene still references the tracked exported texture/SpriteFrames before updating. A different binding fails before writes, preserving the user's new binding. |
| Static update already present | First preservation build could rewrite a static PNG and label it a conflict even when the desired artwork was already in Godot | Not consistent with the minimal-update contract | Compare prepared output pixels with the destination; acknowledge only the source manifest when they match, preserving PNG bytes and timestamps. |
| Resume plus duration | Full export applied a positive FPS and new holds together | Rejected duration changes whenever current Godot FPS was zero, even if the same export restored positive FPS | Permit the combined change, display the prior duration as paused, and retain explicit FPS conflict confirmation. |

The background-removal change was intentional in the implementation but outside the requested product contract. The new tests originally asserted that cleanup must never run. They therefore verified an incorrect requirement instead of detecting this regression. Those assertions are now replaced by tests covering the established opaque-versus-transparent behavior and incremental processing.

## Deliberate changes that remain

| Area | Change and user-visible consequence |
| --- | --- |
| Export action | Existing sprite/project Export actions remain; no additional export mode is required. |
| First export | Still creates scene, texture, and SpriteFrames, using the established art preparation. No update confirmation is shown. |
| Existing export | Compare source content with the last successful baseline. Update only changed images/settings instead of regenerating everything. |
| Confirmation | Show actual affected frames/settings, additions in a mixed project export, and values changed on both sides. Cancel is the default. Approving listed conflicts replaces those values. |
| Godot tuning | Preserve untouched Godot FPS, loop, other holds, extra animations, scripts, collision nodes, event tracks, scene metadata, and existing identifiers. Preservation means retaining their bytes/values; it does not adapt authored gameplay to a structural change. |
| Duration meaning | Explicit Sprite Sage duration changes use milliseconds at the effective Godot FPS. Changing FPS can still affect all frame playback times, as it did previously. Duration changes while FPS remains zero are blocked. |
| No-op | Report up-to-date; don't regenerate files, rerun removal, or change Godot file timestamps. A source change already present in Godot can update only the manifest. |
| Direct destination | Browse to the actual Godot asset folder and remember it per export key. Copying files from a separate staging folder does not preserve destination-only edits. Use a separate folder for each single-sprite export. |
| Existing files without a manifest | Refuse same-name overwrite instead of replacing them. This protects old exports, but requires a fresh folder; automatic adoption is not implemented. |
| Structural source edits | Added/removed/renamed animations, frame count/order, sprite identity/name, declared canvas, and texture-filter changes are blocked for existing exports. Legitimate duplicate-frame replacements can also hit the conservative reorder check. Use a fresh folder. These are restrictions relative to main, not complete support for every explicit edit. |
| Godot resource restructuring | Removed/renamed tracked animations, moved/repacked atlases, changed texture bindings, or unsupported text layouts fail before writes. Godot-resaved relative/res:// paths are checked against their actual destination. |
| Project export | Prepare every eligible sprite before any new writes. One failure stops the batch; apply failures roll back affected files. Hidden sprites and relative subfolder mapping are unchanged. Newly added sprites can be created in a mixed export; removed source sprites are not automatically deleted from Godot. |
| Save before export | Sprite editor now stops if saving explicitly returns failure; the prior flow could continue using old disk data. Save still precedes the destination dialog, so cancelling export can leave the normal source save in place. |
| Cancel / failure | Cancel discards staged export changes. Source or destination edits after preview abort apply. A pending interrupted transaction is recovered before preparation, so recovery itself can restore files even if the later export is cancelled. |
| Recovery files | Add hidden manifest, previous-file snapshot, and pending journal, plus project-local destination preferences. Backups cover affected export files, not complete source artwork. Keep the manifest with the asset. |
| Disk / memory / progress | Hash/read source and destination files; stage output and store before-images. This uses additional temporary space and memory. Export now has preparation and application progress phases, including cleanup during preparation. Unchanged artwork avoids inference. |
| Texture UIDs | New exports omit guessed imported-texture UIDs and let Godot own them. Scene/SpriteFrames IDs are still created on first export and retained on re-export. |
| Python exporter API | Construction no longer creates the destination directory. `prepare()` returns a plan; `export()` applies it and now returns output directories for a single sprite as well as projects. Raw `export_tres`, `export_tscn`, and `export_sprite2d` writers became private `_write_new_*` helpers so they cannot bypass preservation. External callers of those old methods need adaptation. |
| CI | Add a real Godot 4.4.1 round trip. This adds an engine download and runtime to CI; it does not change the shipped app's engine dependencies. |

## Verification and limits

The audit covers every changed production file in the preservation commit. Image generation, editor playback and timing controls, frame ordering in first exports, hidden-sprite selection, source document formats, background-removal model/backend, model caching, and resampling choices were not changed by this branch.

Corrective checks exercise white/opaque source routing, existing meaningful alpha, initial and replacement resizing, static output naming and resizing, compatibility with first-preview manifests, no-op inference avoidance, cleanup failure without destination writes, destination reset, resource rebinding, and paused-animation resumption. Model calls in these deterministic tests use controlled outputs; the existing BEN2 backend is restored, not replaced, and segmentation quality has not been newly benchmarked.

Previously exported white artwork from the first preview remains unchanged on a no-op export by design. To regenerate it with background removal, use a fresh export folder or make an explicit source-art change and approve the resulting image update. Do not erase the manifest to force overwrite. Older assets without a manifest and structural merges remain limitations of this first implementation.

Final source validation: **583 passed, 3 existing skips**, including the real Godot 4.4.1 round trip. Black, Ruff, focused Pyright, and diff whitespace checks passed.

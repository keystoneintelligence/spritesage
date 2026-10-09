# Godot export behavior audit

Compared `e95f479` (the first preservation build) with its main-branch base `d9077d7`, then traced new-export, repeat-export, static, animated, project, cancellation, failure, and recovery paths. This report records both accidental regressions and deliberate contract changes. Corrections are on `codex/godot-export-preservation`, PR #37.

## Regressions corrected

| Behavior | Main / previous workflow | First preservation build | Correction and verification |
| --- | --- | --- | --- |
| Animated background removal | Resize frames and automatically remove backgrounds where meaningful alpha is absent; batch model calls | Passed `extract_alpha=False`, bypassing the pipeline entirely | Restore the same alpha detection and batched cleanup for first exports and only changed frames. Regression checks verify pipeline calls, output alpha, source files unchanged, and siblings untouched. |
| Static background removal | Always call the existing background-removal utility | Copy raw RGBA | Restore the existing model pipeline for first exports and changed static images. No-op exports avoid processing. |
| Replacement-frame sizing | Animated export resizes using NEAREST for pixel art or LANCZOS otherwise | First export resized, but a later replacement with different source dimensions failed | Both first and later exports use the same resize pipeline; existing atlas/canvas dimensions remain stable. |
| Static image sizing | Preserve actual source image dimensions | A replacement with different image dimensions failed | Restore source dimensions for static replacement; the scene stays untouched. Declared canvas changes now produce a reviewed atlas update. |
| Static output filename | Source image basename, such as `base.png` | Sprite name, such as `Static.png` | Restore source basename on first export. Record that destination in the manifest and keep it on later source renames. First-preview manifests without the new field retain their existing `<asset>.png` destination. |
| Alpha composition | Composite onto a transparent cell; semitransparent alpha applied once | Raw RGBA copy retained hidden RGB under completely transparent pixels | Restore legacy cell composition on first and changed-frame exports. A test checks semitransparent alpha remains 128, rather than being applied twice. |
| Destination dialog | Folder name remained editable on each export | A remembered direct folder disabled the name field with no return to normal mode | Add “Use project exports folder,” restoring editable folder names and clearing the remembered custom destination after success. |
| Scene binding validation | Regeneration made the scene reference the generated asset | Preserved any scene bytes, even after a user rebound it to another resource; could update an unused file and report success | Follow an existing bound text SpriteFrames resource, including inline resources. Repair a missing binding with confirmation. Externally bound resources remain untouched; when their fields must change, offer an owned copy retaining authored data and review the scene rebinding. |
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
| Duration meaning | Explicit Sprite Sage duration changes use milliseconds at the effective Godot FPS. Changing FPS can still affect all frame playback times, as it did previously. While FPS remains zero, store the requested duration as a frame weight at the source time base and disclose that playback remains paused. |
| No-op | Report up-to-date; don't regenerate files, rerun removal, or change Godot file timestamps. A source change already present in Godot can update only the manifest. |
| Direct destination | Browse to the actual Godot asset folder and remember it per export key. Copying files from a separate staging folder does not preserve destination-only edits. Use a separate folder for each single-sprite export. |
| Existing files without a manifest | Adopt existing text exports through a staged candidate. Preserve authored playback, metadata and scene content; review actual artwork/frame-list changes because no source baseline exists. |
| Structural source edits | Frame deletion/insertion/duplication/reordering now produce an update preview and can be accepted in the existing folder. Retain surviving atlas cells, per-frame fields, and timing; append new cells. The earlier hard count/order guard contradicted the intended contract and has been removed. Animation addition/removal/rename, sprite identity/name, canvas/filter changes and adding animation to a static sprite use the same staged review. Existing file paths stay stable after sprite renames. |
| Godot resource restructuring | Track frames by texture references and regions, retain Godot-only frames/animations, follow renamed animations, and append a separate cell when a changed mapping or shared texture cannot be updated without affecting siblings. Missing tracked animation content can be restored with review. Preserve opaque Variant fields and resource/node sections; support relative/res:// references and inline SpriteFrames. |
| Project export | Prepare every eligible sprite before any new writes. One failure stops the batch; apply failures roll back affected files. Hidden sprites and relative subfolder mapping are unchanged. Newly added sprites can be created in a mixed export; removed source sprites are not automatically deleted from Godot. |
| Save before export | Sprite editor now stops if saving explicitly returns failure; the prior flow could continue using old disk data. Save still precedes the destination dialog, so cancelling export can leave the normal source save in place. |
| Cancel / failure | Cancel discards staged export changes. Source or destination edits after preview abort apply. Interrupted recovery is also staged and diffed. Preparing or cancelling never writes destination files or retires its pending journal. |
| Recovery files | Add hidden manifest, previous-file snapshot, and pending journal, plus project-local destination preferences. Backups cover affected export files, not complete source artwork. Keep the manifest with the asset. |
| Disk / memory / progress | Hash/read source and destination files; stage output and store before-images. This uses additional temporary space and memory. Export now has preparation and application progress phases, including cleanup during preparation. Unchanged artwork avoids inference. |
| Texture UIDs | New exports omit guessed imported-texture UIDs and let Godot own them. Scene/SpriteFrames IDs are still created on first export and retained on re-export. |
| Python exporter API | Construction no longer creates the destination directory. `prepare()` returns a plan; `export()` applies it and now returns output directories for a single sprite as well as projects. Raw `export_tres`, `export_tscn`, and `export_sprite2d` writers became private `_write_new_*` helpers so they cannot bypass preservation. External callers of those old methods need adaptation. |
| CI | Add a real Godot 4.4.1 round trip. This adds an engine download and runtime to CI; it does not change the shipped app's engine dependencies. |

## Verification and limits

The audit covers every changed production file in the preservation commit. Image generation, editor playback and timing controls, frame ordering in first exports, hidden-sprite selection, source document formats, background-removal model/backend, model caching, and resampling choices were not changed by this branch.

Corrective checks exercise white/opaque source routing, existing meaningful alpha, initial and replacement resizing, static output naming and resizing, compatibility with first-preview manifests, no-op inference avoidance, cleanup failure without destination writes, destination reset, resource rebinding, and paused-animation resumption. Model calls in these deterministic tests use controlled outputs; the existing BEN2 backend is restored, not replaced, and segmentation quality has not been newly benchmarked.

Previously exported white artwork from the first preview remains unchanged on a no-op export by design. To regenerate it with background removal, use a fresh export folder or make an explicit source-art change and approve the resulting image update. Retain the manifest for precise source-change tracking. Existing text exports without one can now be adopted with review. Structural changes are supported through the same confirmation contract.

Final source validation: **583 passed, 3 existing skips**, including the real Godot 4.4.1 round trip. Black, Ruff, focused Pyright, and diff whitespace checks passed.


## Frame-list workflow correction

The hard failure for a changed source frame count was a product-contract error.
Deleting a frame now prepares a reviewable update describing the old/new count
and removed original positions. Accept updates the animation list; Cancel leaves
the export unchanged. Reordering, insertion, duplication, and deletion down to an
empty animation use the same flow. Surviving frame dictionaries and atlas cells
are reused, preserving Godot durations and unknown per-frame metadata. New
artwork uses the established cleanup/resize pipeline and occupies appended cells
without moving existing ones. Deletion/reordering do not rewrite the PNG or scene.

A removed frame with Godot-only timing, image edits, or unknown frame fields is
identified as a conflict before approval. Confirmation explicitly warns that
frame-index gameplay references remain as authored and may need adjustment;
this is disclosure for the user's decision, not a reason to deny the export.

Verification includes a model-origin sprite's GUI export path for both Accept and
Cancel, surviving holds/metadata/atlas identity, next-export baselines, project
preparation, duplicate durations, empty animations, and a real Godot round trip
that deletes and inserts frames while retaining scripts, collisions, metadata,
events, and nonloop playback.

Frame-list correction validation: **591 passed, 3 existing skips**, including the extended real Godot deletion/insertion round trip. Black, Ruff, focused Pyright, and whitespace checks passed.

## Candidate-file review and test-driven correction

The remaining refusal rules were product-contract errors. They are replaced by a
reconciler for the Godot 4 text shapes documented in
[godot-export-contract.md](godot-export-contract.md).

Regression tests were written and run red before each correction. They cover all
previously refused source edits, changed Godot frame counts/order/regions,
shared textures, renamed animations on either side, stable paths, successive
timing/art updates, inline and external bindings, gameplay wrappers,
older/malformed export records, and static-to-animated exports. Snapshot tests
assert every destination byte and modification time during preparation and
native Cancel. Accept writes the exact reviewed candidate bytes.

Candidates are materialized in temporary files. The confirmation lists actual
changed fields/images, with the complete human-readable list and text diffs under
Show Details. Bookkeeping-only changes do not create an update confirmation.
Project exports review the final aggregate candidate.

Interrupted recovery also follows the contract: virtual inputs during preparation,
recovery replacements included in the review, and journals retired only when
accepted. Changes after preview invalidate the candidate before any writes;
I/O failures roll back the transaction.

Candidate-review correction validation: **640 passed, 3 existing skips**, including nine real Godot 4.4.1 round trips. Black, Ruff, focused Pyright and diff whitespace checks passed. New contract tests were observed failing before their corresponding production corrections.

Texture-preservation follow-up validation: **645 passed, 3 existing skips**,
including ten real Godot round trips. Additional tests were observed failing
before fixes for a replaced texture adding an unintended frame, resized atlas
cells losing authored properties, private texture IDs changing unnecessarily,
and a canvas edit falsely reporting a Godot mapping conflict. Resaved atlas IDs
and reordered frames retain their identities. Private atlas resources are patched
in place; shared atlas copies retain authored fields. A real engine load verifies
margin, clipping, metadata and rendered pixels after resizing.

## Review before artwork processing

The GUI now reviews animation operations before background removal. The same
preservation planner builds a non-committable raw-image layout preview; accepted
exports run the original cleanup pipeline and build final guarded candidate
bytes. Cancel performs no model inference and no destination writes. PNG diff
summaries describe artwork changes without pixel bounding boxes. The main dialog
uses frame additions/removals, artwork changes, timing and looping, retaining
conflict/gameplay notes and resource details. Input fingerprints and in-memory
sprite checks prevent changes after review from being silently included.

Review-before-cleanup validation: **661 passed, 3 existing skips**, including ten
real Godot round trips. Sixteen early-review cases verify cleanup order, opaque
and static output processing, native summary wording, no inference/writes on
Cancel, non-committable previews, project reviews and stale approval boundaries.
Regression failures were observed before the corresponding fixes. Black, Ruff,
focused Pyright and diff whitespace checks passed.

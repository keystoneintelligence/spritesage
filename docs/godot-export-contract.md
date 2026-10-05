# Godot export contract

One Export action serves new assets and revisions. A first export creates assets
without an update prompt. An existing asset gets a candidate built from explicit
source changes and current authored Godot content. Review actual changes and choose
Export or Cancel.

## Godot 4 text shapes and field ownership

| Shape | Intentionally editable fields | Preservation rule |
| --- | --- | --- |
| SpriteFrames animation dictionary | name, frames, speed, loop | Patch source changes; keep other keys and Godot-only animations. Identify renames by stable source paths or exported texture identities. |
| Frame dictionary | texture, duration | Keep unknown keys and surviving authored holds. Carry data with frame identity through sequence edits. |
| AtlasTexture subresource | Atlas binding/region for new cells | Keep other fields and private resource IDs when relocating cells. Clone authored texture properties for shared mappings so unedited siblings keep their pixels. |
| External resource sections | Managed sheet reference for new source cells | Keep unrelated dependencies/IDs. Insert external resources before subresources for valid Godot syntax. |
| External SpriteFrames binding | Actively bound text resource | Follow an existing managed binding. Outside the destination, art-only updates keep the binding; field changes offer an owned copy retaining authored values and dependencies. Original external files stay untouched. |
| Inline SpriteFrames binding | Owned animation/frame fields | Keep the binding, subresource ID and surrounding scene content. |
| Exported visual node | Explicit name/filter changes; binding repairs; references invalidated by explicit animation rename/removal | Select the bound sprite when wrapped in a gameplay root. Keep transforms, offsets, flips, scripts, collision properties, children and metadata. Keep scene filenames/UIDs stable. |
| Static-to-animated visual | Node type, playback binding/default, incompatible static fields | List the conversion/removals. Keep game data and children; warn about scripts depending on the old class. |
| Other serialized content | None unless in disclosed recovery/replacement | Preserve opaque Variant values, metadata, resource/node properties and connections. Do not serialize unknown authored values through JSON. |
| PNG pixels | Changed/new art; cells/dimensions needed by canvas edits | Keep the established resize/background-removal pipeline. Preserve unaffected cells and avoid inference for untouched art. |

Godot supports arbitrary script properties and Variant metadata: the schema is an
editable envelope with opaque values, not a closed allowlist that deletes unknown
fields. This implementation targets exported Godot 4 text scenes/resources.
Corrupt/unreadable source assets and invalid resource syntax remain technical errors.

A paused animation stays at 0 FPS. Changed duration is stored as a frame weight
at the SpriteSage time base and disclosed; elapsed milliseconds are undefined
while paused. FPS/loop change only when changed in the source.

Scripts, event tracks and animation-name/frame-index metadata stay authored.
The preview discloses references needing review rather than guessing game logic.
Structural changes can be accepted.

## Candidate and commit

1. Fingerprint sources/destinations and compare source with its last successful
   snapshot. Adopt older exports without a baseline while keeping Godot tuning.
2. Patch owned spans or allocate cells/references; preserve unknown values.
   Stage interrupted recovery through virtual inputs without destination writes.
3. Materialize candidates in temporary files, read their exact bytes and diff the
   destination. Exclude byte-identical writes.
4. List actual field/image additions, replacements and removals. Put the complete
   readable list and exact text diffs under Show Details. Disclose conflicts and
   preservation consequences in that same confirmation.
5. Cancel discards the plan. Export verifies fingerprints and commits the reviewed
   bytes. Retire pending journals only after acceptance. Back up affected files
   and roll back if committing fails.

Records/backups and destination preferences are bookkeeping, not export modes.
A no-op preserves Godot files and timestamps; acknowledging a source change already
present in Godot may update only the record.

## Executable contract tests

tests/test_godot_export_contract.py snapshots all destination files, including
bookkeeping, during preparation/Cancel. Accept compares writes to reviewed
candidate bytes and every unaffected asset to its original bytes/timestamp.
The additional accepted write is the transaction backup. Native Qt tests click
Cancel in the actual review dialog. Interrupted recovery is staged too.

tests/test_godot_preservation.py retains minimal-update, alpha, resize, per-cell,
race, rollback and recovery checks. Former refusal tests now require reviewable
plans without destination writes.

tests/test_godot_runtime.py imports/loads candidates in Godot 4.4.1 and verifies
rendered pixels, FPS/loop/holds, metadata, scripts, collisions and event tracks,
plus structural edits, inline/external bindings, changed texture references and
texture metadata/properties after resizing.
Engine tests catch parser/runtime issues beyond textual snapshot assertions.

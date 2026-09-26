# Sprite generation context audit

Audited the editor entry points, OpenAI/Google/local adapters, local prompt
improvement, template generation, saved jobs, retries, imports, and polish.

## Findings and fixes

| Path | Previous gap | Current behavior |
| --- | --- | --- |
| New sprite / regenerate base image | Project text, camera and references arrived, but an existing base image and rendering mode did not. | Includes project context plus the current base image as the identity reference, sprite description, canvas dimensions, and rendering mode. |
| Add AI frame before/after | Only animation name, camera and one or two neighboring frames arrived. | Adds project description, keywords and style images, sprite description, base identity image, dimensions and rendering mode. |
| Add animation with automatically generated frames | Used the same incomplete add-frame path. | Uses the corrected frame path on every iteration. |
| From Template: generate character image | Ignored project images and existing character; used a fixed camera instruction. | Uses project style images, selected character identity, project camera and sprite rendering mode. |
| From Template: generate animation | Passed only pose, character image and character description. | Also passes project text, style references and rendering mode for every frame. Defaults the template camera from the project; an explicit template view determines the pose camera. |
| From Template: resume / retry | No project context in requests or cache keys. | Saves context and copies of character/style images. Includes style text, settings and image hashes in the recipe fingerprint. Retries use saved references; changed settings or image contents select a different job. |
| Google image requests | Could skip unreadable images and continue with incomplete context. | Stops generation when a configured image cannot be loaded. |
| Local prompt improvement | Could reinforce pixel art regardless of sprite rendering mode. | Receives the full context and numbered image roles; appends style constraints after rewriting. Pose-guided transfer also restores the context after rewriting. |

`src/spritesage/art_context.py` holds the common context and image-role logic.
Animation endpoints stay first, followed by the base identity and project style
images. Supplemental duplicates are removed without collapsing two identical
animation endpoints. Project images guide palette, lighting, texture and rendering;
they are explicitly distinguished from identity and pose references.

No reference images are silently truncated to fit local model limits. A request
that exceeds the selected model's capacity fails with an explanation. OpenAI and
Google continue to enforce their own model limits. More references may increase
request cost and generation time.

## Paths that preserve supplied art

- New Sprite creates metadata; its Generate Base Image action is covered above.
- Import Existing Art (sequences, folders, sheets, animated GIF/WebP, Aseprite)
  preserves supplied pixels and timing. It does not restyle imported art.
- Import 3D Model and the model-baker CLI render the supplied model/materials with
  their bake settings. They do not use project reference images as style inputs.
- Manual frame import, duplicate/reorder/reverse/ping-pong, drawing, local polish,
  and background removal operate on existing artwork without image generation.
- Description, keyword and animation-name suggestions generate text, not artwork.

## Remaining limits

There is no separate sprite reference gallery or explicit art-style field in the
current `.sprite` schema. Sprite identity comes from its description and base image,
with adjacent frames providing motion continuity. A dedicated multi-image character
reference gallery would be a separate feature.

Legacy template drafts retain their original recipe when resumed, so their existing
frames can still be reused. Start a new job to apply the full project context.
New drafts preserve the art context from when they were created, even after project
settings change.

Canvas dimensions are prompt guidance in ordinary generation; provider output sizes
and later resizing still determine the actual file dimensions. Supplying all context
improves consistency but does not guarantee that a generative model follows it.

Regression tests inspect actual mocked provider requests for all three providers,
editor actions, template character generation, local prompt rewriting, draft resume,
retry, reference ordering, missing images and local reference limits. They do not
make paid API calls or evaluate visual model output.

## Verification

- Full suite: `pytest -n 4` — 459 passed, 3 environment-dependent skips.
- `black --check src tests` and `ruff check src tests` passed.
- Focused Pyright checks on context, inference, local inference and template
  dialog/service modules passed with the project virtual environment.

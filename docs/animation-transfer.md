# Animation transfer (experimental)

Open a project and choose **Animate from Template…**. Describe the character, generate its image with the selected local model (or choose an image you already have), then choose a character type, motion template, animations and camera directions. **Preview motion** plays the first selected motion and direction without AI generation. The generation button shows the number of images that will be generated.

For an existing sprite, use **From Template…** below the animation list. Its image and description are prefilled. Finished animations are added as one undoable action; existing names are preserved and duplicate names receive a suffix. Existing sprite dimensions and playback settings are preserved.

If that sprite has **Include base image** enabled, its existing preference also applies to newly added animations. Turn it off to preview the transferred cycle without an extra starting pose. Newly created transfer sprites default to excluding the base image from playback.

## Setup

**Manage local models…** opens the shared Model Manager catalog. Install or connect an image-editing model there. This workflow always uses the selected local model, independently of the provider selected for other Sprite Sage tools. Qwen Image 2.1 is the initial supported model.

**Add template…** registers an animated, self-contained GLB from any location. It reads animation names and durations from the model rather than a hardcoded list. Template registrations live in `animation-templates.json` in Sprite Sage's application data directory. Files are borrowed in place. If a model moves, add it again from its new location; identical contents update the existing registration. The catalog supports multiple templates and character types. Additional types can be supplied through catalog entries.

The initial demonstration uses the existing Bandit humanoid with `Walking`, `Running`, `Run_03` and `Dead`. The private source asset is not part of the application distribution; register your copy once with **Add template…**. Future distributable motion packs can use the same catalog without coupling image-model management to 3D assets.

## Defaults and outputs

- One walking motion and one level camera direction are selected by default.
- Up to eight frames cover the **whole** clip at its original duration. Limiting frame count never truncates the motion.
- Generation uses 512 × 512 images and produces 128 × 128 transparent frames. Sizes, sampling rate, frame limit, framing and background cleanup are under **Advanced settings**.
- Camera labels refer to the side of the model viewed by the camera. A model's own forward axis determines which way the character faces on screen. Use the motion preview to check.
- Every frame uses the same character reference and its own rendered pose guide. The camera stays fixed across the poses. A fixed seed and explicit pose instructions reduce drift; temporal consistency is still model-dependent.
- Character-image generation retains the normal prompt-helper behavior. Pose-transfer prompts are fixed across the batch so prompt rewriting cannot introduce a different interpretation into each frame.
- White-background cleanup removes border-connected white while retaining enclosed light details such as eyes and tusks. The character's height and feet are aligned to the pose guide. Raw images remain available for manual cleanup.

The project receives an ordinary editable `.sprite` plus a folder under `sprites/<name>_transfer_<recipe hash>/` containing pose guides, raw Qwen outputs, transparent frames, PNG sheets, GIF previews, a relative-path manifest and the generation recipe. GIFs use a shared palette, original timing rounded to GIF's 10 ms units, and loop flags from the source animation. Nonlooping death clips remain nonlooping.

## Long jobs and recovery

Generation is sequential and can take several minutes per frame on older GPUs. Progress identifies the motion, direction and frame. Cancel releases the owned engine process and retains completed work. Retry with identical inputs to resume. Completed frames are checked by SHA-256; corrupt prepared frames can be recreated from verified raw images without another model call. Changes to the character, model revision, seed, sampling or output settings create a separate job instead of mixing incompatible frames.

After reopening the dialog, **Resume saved job…** restores an unfinished job's character image, template, motions, directions and local settings. Review them and click Generate to continue. Keep the original character image and GLB available while a job is unfinished. Each job also saves a `request.json` for the command-line diagnostic.

Animation transfer is an experimental image-editing workflow, not skeletal retargeting. Review the generated movement and character consistency before using it in a game.

See the [local create/edit comparison and complete orc experiment](animation-transfer-evaluation.md) for actual results and current pose-adherence limitations.

## Release diagnostic

`spritesage.exe --test-animation-transfer request.json` runs the same production pipeline without opening the UI. The JSON contains `request` (the `TransferRequest` fields; file paths are strings) and an optional Model Manager `config`. When `config` is omitted, saved local settings are used. The command prints the manifest/GIF paths and generated/reused frame counts. It does not overwrite an existing `.sprite` document.

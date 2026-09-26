# Animation transfer (experimental)

Open a project and choose **From Template (Experimental)**. Describe the character, generate its image with the image model selected in Preferences (or choose an image you already have), then choose a character type, motion template, animations and camera directions. **Preview motion** plays the first selected motion and direction without AI generation. The generation button shows the number of images that will be generated. When generation finishes, review each rendered pose beside its generated sprite before accepting the animation.

For an existing sprite, use **From Template…** below the animation list. Its image and description are prefilled. Finished animations are added as one undoable action; existing names are preserved and duplicate names receive a suffix. Existing sprite dimensions and playback settings are preserved.

If that sprite has **Include base image** enabled, its existing preference also applies to newly added animations. Turn it off to preview the transferred cycle without an extra starting pose. Newly created transfer sprites default to excluding the base image from playback.

## Setup

Animation transfer uses Sprite Sage's global **Selected Inference Provider** and image model from **Preferences**: OpenAI, Google, or Local. There is no second model selector in the transfer dialog. OpenAI GPT Image 2.5 Flare and Sunburst appear as choices even when the model-list response omits them; actual access depends on your OpenAI account. OpenAI transfer uses 1024 × 1024 generation and the Images edit endpoint with the pose and character images. Google transfer requires a Gemini image model that accepts both images; Imagen does not use this editing path. An incompatible selected model is rejected before generation.

For Local, **Manage local models…** opens the shared Model Manager catalog. Install or connect an image-editing model and its **Prompt improvement** tools there. The pose-guided experimental mode uses those local tools to read each source pose and rewrite the edit prompt. Qwen Image 2.1 is the initial supported local model. The older fixed-prompt mode remains available under **Advanced settings** and does not require prompt tools. Cloud models receive the rendered pose and character reference directly, plus measured pose facts when available; they do not require local prompt tools.

**Add template…** registers an animated, self-contained GLB from any location. It reads animation names and durations from the model rather than a hardcoded list. Template registrations live in `animation-templates.json` in Sprite Sage's application data directory. Files are borrowed in place. If a model moves, add it again from its new location; identical contents update the existing registration. The catalog supports multiple templates and character types. Additional types can be supplied through catalog entries.

Bandit is included as the starter Humanoid motion template, with `Walking`, `Running`, `Run_03` and `Dead`. On first use, Sprite Sage copies the bundled GLB to its application data directory with a content-based filename, so saved jobs can find it after an app restart. The template appears automatically; no download or **Add template…** step is needed. You can still register other animated GLBs from any location. The Bandit asset was created by the project owner with a paid Meshy plan, likely using an OpenAI-generated reference image.

## Defaults and outputs

- One walking motion and one level camera direction are selected by default.
- Up to eight frames cover the **whole** clip at its original duration. Limiting frame count never truncates the motion.
- Local and Google generation default to 512 × 512 pose guides. OpenAI uses 1024 × 1024, as required by GPT Image 2.5. Output defaults to 128 × 128 transparent frames. Sizes, sampling rate, frame limit, framing and background cleanup are under **Advanced settings**.
- Camera labels refer to the side of the model viewed by the camera. A model's own forward axis determines which way the character faces on screen. Use the motion preview to check.
- Every frame uses the same character reference and its own rendered pose guide. The camera stays fixed across the poses. In local pose-guided mode, the prompt helper describes each pose in screen coordinates, and recognized humanoid rig joints constrain facing, boot height, and approximate hand and boot positions. Obvious contradictions about which boot is raised cause a fallback to the direct edit prompt. Cloud models receive a direct two-image edit prompt with the measured rig facts. Templates without recognized joints use the rendered pose alone and are flagged in review.
- **Advanced settings** contains the pose-guided toggle. Turning it off retains the original fixed-prompt behavior. Character-image generation retains its own prompt-helper behavior.
- White-background cleanup removes border-connected white while retaining enclosed light details such as eyes and tusks. The character's height and feet are aligned to the pose guide. Raw images remain available for manual cleanup.

After acceptance, the project receives an ordinary editable `.sprite` plus a folder under `sprites/<name>_transfer_<recipe hash>/` containing pose guides, raw model outputs, transparent frames, PNG sheets, GIF previews, a relative-path manifest and the generation recipe. GIFs use a shared palette, original timing rounded to GIF's 10 ms units, and loop flags from the source animation. Nonlooping death clips remain nonlooping. Saved requests and recipes contain provider and model IDs, but never API keys.

## Frame review and retry

The review window lists every generated frame. Select one to compare **Expected pose** and **Generated sprite** side by side. **Retry this frame** creates a new version. Local retries use a new seed; cloud retries make one more API request. An optional note such as “Keep the rear boot raised” targets that correction. The **Frame version** menu can restore the original or any retry without another model call. The selected version updates the saved PNG, sheet, and GIF preview. **Accept animation** adds only the chosen versions to Sprite Sage. **Close · keep draft** saves the draft without adding it to the project.

## Long jobs and recovery

Generation is sequential and can take several minutes per frame on older GPUs. Progress identifies the motion, direction and frame. The dialog shows the maximum initial cloud request count and asks for confirmation before a cloud job; generating the character image and each frame retry are additional requests. Cancel retains completed work. Retry with identical inputs to resume. Completed frames are checked by SHA-256; corrupt prepared frames can be recreated from verified raw images without another model call. Changes to the character, selected provider or model, model revision, seed, sampling or output settings create a separate job instead of mixing incompatible frames. A cloud draft can resume or retry only while the same global provider and model are selected.

After reopening the dialog, **Resume saved job…** restores an unfinished job's character image, template, motions, directions and local settings. Cloud jobs use the current credential from Preferences and require the saved provider and image model to still be selected. A fully generated draft opens for review; an incomplete job resumes generation. Keep the original character image and GLB available until the draft is accepted. Each job also saves a key-free `request.json` for the command-line diagnostic.

Animation transfer is an experimental image-editing workflow, not skeletal retargeting. Review the generated movement and character consistency before using it in a game.

## Release diagnostic

`spritesage.exe --test-animation-transfer request.json` runs the same production pipeline without opening the UI. The JSON contains `request` (the `TransferRequest` fields; file paths are strings) and an optional key-free provider/model `config`. When `config` is omitted, global Preferences are used. The command prints the manifest/GIF paths and generated/reused frame counts. It does not overwrite an existing `.sprite` document. Running a cloud diagnostic may incur image API charges.

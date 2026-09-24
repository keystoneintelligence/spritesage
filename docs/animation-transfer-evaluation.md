# Local Qwen animation-transfer experiment

The first experiment uses the existing Bandit humanoid's Walking clip and a green orc character generated locally with Qwen Image 2.1 INT8. The motion runs for 1.033 seconds; six samples cover the full cycle from the model's right-side camera.

## Create versus edit

![Character reference, pose guide, creation result and edit result](examples/create-vs-edit.png)

Both modes used the same installed model, 512 × 512 generation, 25 sampling steps and seed 4817. Qwen exposes a unified local workflow: creation omits reference images, while editing supplies them. Creation used the installed prompt helper; editing used explicit fixed instructions. These are representative qualitative trials, not a statistical benchmark.

| Mode | Result on the stride test | Elapsed time |
| --- | --- | --- |
| Create from a pose/character description | Strong action pose, but changed face, proportions, clothing and camera angle; trousers became exposed legs. | 246 s including prompt improvement |
| Edit with pose + character references | Retained the reference orc and outfit, corrected facing and produced a walking stride. Arm placement remained approximate. | 271 s |

**Use creation for the character design, then editing for the animation experiment.** Independent creation offers too much variation for identity-sensitive frames. Editing preserves identity better, but neither approach demonstrated reliable animation-ready output in these trials.

The initial untagged edit trials either copied the standing character or preserved the source bandit. Qwen's [official editing instructions](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_edit.txt) require `<image1>`, `<image2>` references. The implementation uses these tags and separates the pose canvas from the identity reference. It also avoids confusing a camera's side with the character's screen-facing direction.

## Completed walking sequence

![Six-frame local Qwen walking experiment](examples/green-orc-walking.gif)

![All six generated frames](examples/green-orc-walking.png)

The complete production run generated six distinct transparent 128 × 128 frames, a 768 × 128 sheet and a looping 512 × 512 GIF. It took **27 minutes 31 seconds** on the installed GTX 1070 configuration, excluding the initial character image and comparison probes. GIF timing is 1.030 seconds against the source clip's 1.033 seconds, accounting for GIF's 10 ms timing resolution.

This is an uncurated experiment: all six outputs are retained in source order. The first four face left and show some leg movement, while the final two revert toward the reference's standing pose and right-facing angle. Arms and armor also vary. **The pipeline works, but this result is not a finished game-ready walking cycle.** File integrity, transparency and timing checks cannot establish visual pose adherence.

Further quality work should test a character reference matching each selected camera angle, explicit per-pose descriptions, and a model/workflow with stronger pose conditioning. The current fixed-reference image-editing approach should remain experimental until those tests demonstrate consistent motion.

## Verification

The production service renders the poses, submits one local edit per frame, aligns the outputs to the pose guides, and creates transparent frames, a sheet, GIF and editable Sprite Sage animation. The full suite passed with **414 tests and 3 environment-dependent skips**. Tests cover timing, multiple directions, cancellation, saved-job restoration, verified frame reuse, corrupt-frame recovery, filename isolation, and undoable editor integration. A packaged-app diagnostic confirmed that a second invocation cannot enter an already-running job, then reopened the completed job in 8.4 seconds with **zero generated frames and six verified reused frames**. Native motion preview and editor layouts were also checked visually.

The bandit source is a separately registered local asset; it is not redistributed in this repository. Generated examples below are the AI outputs, not the 3D source model.

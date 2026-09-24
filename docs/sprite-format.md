# Sprite format, version 2

The root `format_version` integer is `2`. Missing versions (and explicit `1`)
identify the legacy format, where each animation was just an array of paths.
Unsupported versions fail to load rather than being rewritten and losing data.
Loading a legacy file does not write it; the next save writes version 2 through
the normal atomic save and recovery-checkpoint mechanism.

All existing sprite fields remain. Animation records now contain:

```json
{
  "format_version": 2,
  "animations": {
    "walk": {
      "fps": 10.0,
      "loop": true,
      "base_frame_duration": 1.0,
      "frames": [
        {"path": "sprites/hero/walk/01.png", "duration": 1.0},
        {"path": "sprites/hero/walk/02.png", "duration": 2.5}
      ]
    }
  }
}
```

This excerpt omits unchanged required sprite properties. Paths are relative to
the project directory; new files use forward slashes, and the reader also accepts
legacy Windows separators. Repeated paths are distinct frame occurrences, each
with its own duration.

`duration` is a positive relative hold: **seconds = duration / fps**. In this
example the frames last 100 ms and 250 ms. Changing FPS scales the entire sequence
without flattening individual holds. The editor displays milliseconds; the model
and both exporters use these same relative holds, matching
[Godot SpriteFrames timing](https://docs.godotengine.org/en/4.4/classes/class_spriteframes.html#class-spriteframes-method-get-frame-duration).

FPS and all durations must be positive finite numbers; `loop` must be a boolean.
The optional leading base image has an independent `base_frame_duration` per
animation and uses the same FPS. Turning off `include_base_image_in_animations`
excludes both that image and its duration from preview and export.

Legacy files default to 2 FPS, Loop on, and a hold of 1 for every frame, including
the base image. This preserves their former preview behavior; their Godot exports
now use the same speed. Plain still-image imports use those defaults too.

Aseprite durations are milliseconds. Import chooses FPS from the shortest hold
and preserves each duration as a relative multiple. Direction becomes explicit
frame order. Unspecified/zero tag repeat retains continuous editor looping;
positive repeat counts expand a one-shot sequence. Aseprite counts individual
traversals for finite ping-pong repeats, as documented in
[Tag.repeats](https://www.aseprite.org/api/tag#tagrepeats).

Animated GIF and WebP files retain their decoded frames and timing. Finite loop
counts expand references to the extracted frames; zero means continuous looping.
Missing/zero animated-image timing falls back to 100 ms. When several source
files are combined into one sequence, the resulting animation loops by default.

Model-baker manifests save `fps`, `loop`, and relative `frame_durations` per clip.
Both export routes share a manifest-to-animation adapter. Older manifests derive
durations from successive sample times and the remaining clip duration, using
their FPS for a missing final duration. Missing loop metadata retains the old
baker convention (death/die/dying/dead clips play once; others loop). Newly baked
clips omit duplicate endpoint poses; capped frame counts sample the full clip.

Preview scheduling uses Qt's precise timer at millisecond resolution (minimum
1 ms), carrying fractional milliseconds between frames to avoid rounding drift.
Saved and exported timing retains floating-point precision.

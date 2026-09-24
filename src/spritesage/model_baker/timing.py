"""One timing adapter for baked Sprite Sage files and direct Godot exports."""

from __future__ import annotations

import math
from typing import Any

from spritesage.sprite_file import Animation, positive_number


def animation_from_manifest(
    record: dict[str, Any], *, name: str, frames: list[str], default_fps: float
) -> Animation:
    fps = positive_number(record.get("fps", default_fps), "Animation FPS")
    # Older manifests used the direct exporter's death-animation convention.
    loop = record.get(
        "loop", str(record.get("name", "")).lower() not in {"dead", "death", "die", "dying"}
    )
    durations = record.get("frame_durations")
    if durations is None:
        times = record.get("times")
        durations = [1.0] * len(frames)
        if times:
            if len(times) != len(frames):
                raise ValueError("Baked frame timestamps must match the frame count.")
            if any(
                isinstance(t, bool)
                or not isinstance(t, (int, float))
                or not math.isfinite(t)
                or t < 0
                for t in times
            ):
                raise ValueError("Baked frame timestamps must be finite and non-negative.")
            durations = [
                positive_number(end - start, "Baked frame interval") * fps
                for start, end in zip(times, times[1:], strict=False)
            ]
            remaining = float(record.get("duration", 0)) - times[-1]
            # Legacy manifests may include an endpoint pose, or omit clip duration.
            durations.append(remaining * fps if remaining > 0 else 1.0)
    if not isinstance(durations, list) or len(durations) != len(frames):
        raise ValueError("Baked frame durations must match the frame count.")
    return Animation(name, frames, fps, loop, durations)

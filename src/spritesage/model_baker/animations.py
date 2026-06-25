from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from pygltflib import GLTF2


@dataclass(frozen=True)
class AnimationClip:
    index: int
    name: str
    duration: float


def inspect_animations(model_path: str | Path) -> list[AnimationClip]:
    """Return animation names and durations from a GLB/GLTF file."""
    gltf = GLTF2().load(str(model_path))
    if gltf is None:
        raise ValueError(f"Could not load GLB/GLTF model: {model_path}")

    clips: list[AnimationClip] = []
    for index, animation in enumerate(gltf.animations or []):
        duration = 0.0
        for sampler in animation.samplers or []:
            if sampler.input is None:
                raise ValueError(f"Animation '{animation.name or index}' has no input accessor")
            accessor = gltf.accessors[sampler.input]
            if accessor.max:
                duration = max(duration, float(accessor.max[0]))
        name = animation.name or f"animation_{index:02d}"
        clips.append(AnimationClip(index=index, name=name, duration=duration))
    return clips


def rest_clip() -> AnimationClip:
    return AnimationClip(index=-1, name="rest", duration=0.0)


def frame_times(duration: float, fps: float, max_frames: int | None = None) -> list[float]:
    if fps <= 0:
        raise ValueError("fps must be greater than zero")

    if duration <= 0:
        return [0.0]

    count = max(1, int(math.floor(duration * fps)) + 1)
    if max_frames is not None:
        if max_frames <= 0:
            raise ValueError("max_frames must be greater than zero")
        count = min(count, max_frames)

    if count == 1:
        return [0.0]

    step_times = [index / fps for index in range(count)]
    return [min(time_value, duration) for time_value in step_times]


def select_clips(
    clips: list[AnimationClip],
    selected: list[str] | None,
) -> list[AnimationClip]:
    if not clips:
        return [rest_clip()]
    if not selected:
        return clips

    by_name = {clip.name.lower(): clip for clip in clips}
    by_index = {str(clip.index): clip for clip in clips}
    chosen: list[AnimationClip] = []
    for value in selected:
        key = value.lower()
        clip = by_name.get(key) or by_index.get(value)
        if clip is None:
            known = ", ".join(clip.name for clip in clips)
            raise ValueError(f"Unknown animation '{value}'. Known animations: {known}")
        chosen.append(clip)
    return chosen


def select_base_pose_clip(clips: list[AnimationClip]) -> AnimationClip | None:
    """Choose the animation most likely to contain a neutral standing pose."""
    priority_groups = (
        ("idle", "rest", "stand", "standing", "neutral", "default", "breath"),
        ("walk",),
    )
    normalized = [
        (clip, "".join(char.lower() for char in clip.name if char.isalnum())) for clip in clips
    ]
    for keywords in priority_groups:
        for clip, name in normalized:
            if any(keyword in name for keyword in keywords):
                return clip
    return None

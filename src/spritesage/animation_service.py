"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

# pyright: strict

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Literal

from .sprite_file import Animation, SpriteFile


@dataclass(frozen=True)
class FrameCopyPlan:
    source_path: str
    stored_path: str
    requires_copy: bool


@dataclass(frozen=True)
class FrameInsertion:
    index: int
    path: str


@dataclass(frozen=True)
class AiFrameInsertionPlan:
    insertion_index: int
    generation_kind: Literal["next", "between"]
    images: tuple[str, ...]


def add_animation(sprite_data: SpriteFile, animation_name: str) -> None:
    if animation_name in sprite_data.animations:
        raise ValueError(f"Animation '{animation_name}' already exists.")
    sprite_data.animations[animation_name] = Animation(name=animation_name, frames=[])


def remove_animation(sprite_data: SpriteFile, animation_name: str) -> bool:
    if animation_name not in sprite_data.animations:
        return False
    del sprite_data.animations[animation_name]
    return True


def plan_frame_copy(
    input_path: str,
    base_dir: str,
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> FrameCopyPlan:
    abs_input = os.path.abspath(input_path)
    norm_base_dir = os.path.normpath(base_dir)
    if abs_input.startswith(norm_base_dir + os.sep):
        return FrameCopyPlan(
            source_path=abs_input,
            stored_path=abs_input,
            requires_copy=False,
        )

    basename = os.path.basename(abs_input)
    target = os.path.join(base_dir, basename)
    name, ext = os.path.splitext(basename)
    counter = 1
    while path_exists(target):
        target = os.path.join(base_dir, f"{name}_{counter}{ext}")
        counter += 1
    return FrameCopyPlan(
        source_path=abs_input,
        stored_path=os.path.normpath(target),
        requires_copy=True,
    )


def plan_frame_duplicate(
    source_path: str,
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> FrameCopyPlan:
    abs_source = os.path.abspath(source_path)
    directory = os.path.dirname(abs_source)
    basename = os.path.basename(abs_source)
    name, ext = os.path.splitext(basename)
    target = os.path.join(directory, f"{name}_copy{ext}")
    counter = 1
    while path_exists(target):
        target = os.path.join(directory, f"{name}_copy_{counter}{ext}")
        counter += 1
    return FrameCopyPlan(
        source_path=abs_source,
        stored_path=os.path.normpath(target),
        requires_copy=True,
    )


def insert_frames(
    sprite_data: SpriteFile,
    animation_name: str,
    insertion_index: int,
    frame_paths: list[str],
) -> list[FrameInsertion]:
    frame_list = sprite_data.animations.setdefault(
        animation_name,
        Animation(name=animation_name, frames=[]),
    ).frames

    inserted: list[FrameInsertion] = []
    index = max(0, min(insertion_index, len(frame_list)))
    for frame_path in frame_paths:
        if frame_path in frame_list:
            continue
        frame_list.insert(index, frame_path)
        inserted.append(FrameInsertion(index=index, path=frame_path))
        index += 1
    return inserted


def duplicate_frame(
    sprite_data: SpriteFile,
    animation_name: str,
    frame_index: int,
    duplicated_path: str,
) -> FrameInsertion | None:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    if frame_index < 0 or frame_index >= len(frames):
        return None

    insertion_index = frame_index + 1
    frames.insert(insertion_index, duplicated_path)
    return FrameInsertion(index=insertion_index, path=duplicated_path)


def remove_frames(
    sprite_data: SpriteFile,
    animation_name: str,
    frame_paths: list[str],
) -> int:
    animation = sprite_data.animations.get(animation_name)
    if animation is None:
        return 0

    current_frames = animation.frames
    new_frames = [frame for frame in current_frames if frame not in frame_paths]
    removed_count = len(current_frames) - len(new_frames)
    if removed_count > 0:
        animation.frames = new_frames
    return removed_count


def remove_frame_indices(
    sprite_data: SpriteFile,
    animation_name: str,
    frame_indices: list[int],
) -> int:
    animation = sprite_data.animations.get(animation_name)
    if animation is None:
        return 0

    frames = animation.frames
    indices_to_remove = {index for index in frame_indices if 0 <= index < len(frames)}
    if not indices_to_remove:
        return 0

    animation.frames = [
        frame for index, frame in enumerate(frames) if index not in indices_to_remove
    ]
    return len(indices_to_remove)


def move_frame(
    sprite_data: SpriteFile,
    animation_name: str,
    current_index: int,
    offset: Literal[-1, 1],
) -> int | None:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    new_index = current_index + offset
    if current_index < 0 or current_index >= len(frames):
        return None
    if new_index < 0 or new_index >= len(frames):
        return None

    frame_to_move = frames.pop(current_index)
    frames.insert(new_index, frame_to_move)
    return new_index


def reverse_animation_frames(
    sprite_data: SpriteFile,
    animation_name: str,
) -> bool:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    if len(frames) < 2:
        return False
    frames.reverse()
    return True


def make_ping_pong_loop(
    sprite_data: SpriteFile,
    animation_name: str,
) -> list[FrameInsertion]:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    if len(frames) < 3:
        return []

    ping_pong_frames = list(reversed(frames[1:-1]))
    insertion_start = len(frames)
    frames.extend(ping_pong_frames)
    return [
        FrameInsertion(index=insertion_start + offset, path=path)
        for offset, path in enumerate(ping_pong_frames)
    ]


def plan_ai_frame_before(
    sprite_data: SpriteFile,
    animation_name: str,
    selected_index: int,
) -> AiFrameInsertionPlan:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    if not frames:
        return AiFrameInsertionPlan(
            insertion_index=0,
            generation_kind="next",
            images=(sprite_data.base_image,),
        )

    insertion_index = max(0, min(selected_index, len(frames) - 1))
    if insertion_index == 0:
        images = (sprite_data.base_image, frames[0])
    else:
        images = (frames[insertion_index - 1], frames[insertion_index])
    return AiFrameInsertionPlan(
        insertion_index=insertion_index,
        generation_kind="between",
        images=images,
    )


def plan_ai_frame_after(
    sprite_data: SpriteFile,
    animation_name: str,
    selected_index: int,
) -> AiFrameInsertionPlan:
    frames = sprite_data.get_animation_frames(animation_name=animation_name)
    if not frames:
        return AiFrameInsertionPlan(
            insertion_index=0,
            generation_kind="next",
            images=(sprite_data.base_image,),
        )

    current_index = max(0, min(selected_index, len(frames) - 1))
    if current_index == len(frames) - 1:
        images = (frames[current_index], sprite_data.base_image)
    else:
        images = (frames[current_index], frames[current_index + 1])
    return AiFrameInsertionPlan(
        insertion_index=current_index + 1,
        generation_kind="between",
        images=images,
    )

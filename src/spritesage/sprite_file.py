"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

# pyright: strict

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, cast
from .persistence import save_document

SPRITE_FORMAT_VERSION = 2
DEFAULT_ANIMATION_FPS = 2.0


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object.")
    return cast(dict[str, Any], value)


def _absolute_path(value: object, directory: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Frame paths must be strings.")
    return os.path.normpath(os.path.join(directory, value.replace("\\", "/")))


def positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive, finite number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive, finite number.")
    return number


@dataclass
class Animation:
    name: str
    frames: list[str]
    fps: float = DEFAULT_ANIMATION_FPS
    loop: bool = True
    # Relative holds: seconds = duration / fps. Stored beside each path in JSON.
    frame_durations: list[float] = field(default_factory=lambda: list[float]())
    base_frame_duration: float = 1.0

    def __post_init__(self) -> None:
        if not self.frame_durations:
            self.frame_durations = [1.0] * len(self.frames)
        self.validate()

    def validate(self) -> None:
        positive_number(self.fps, "Animation FPS")
        if type(self.loop) is not bool:
            raise ValueError("Animation loop must be true or false.")
        if len(self.frames) != len(self.frame_durations):
            raise ValueError("Each animation frame must have a duration.")
        for duration in self.frame_durations:
            positive_number(duration, "Frame duration")
        positive_number(self.base_frame_duration, "Base frame duration")

    def frame_seconds(self, index: int) -> float:
        return self.frame_durations[index] / self.fps

    def select_frames(self, indices: list[int]) -> None:
        """Apply an order, subset, or repeated sequence without detaching timing."""
        self.frames, self.frame_durations = (
            [self.frames[index] for index in indices],
            [self.frame_durations[index] for index in indices],
        )


@dataclass
class SpriteFile:
    uuid: str
    name: str
    description: str
    width: int
    height: int
    base_image: str
    animations: dict[str, Animation]
    include_base_image_in_animations: bool = True
    pixel_art: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], sage_directory: str) -> "SpriteFile":
        data = _mapping(data, "The sprite file")
        version = data.get("format_version", 1)
        if type(version) is not int or version not in (1, SPRITE_FORMAT_VERSION):
            raise ValueError(f"Unsupported sprite format version: {version}.")
        animations: dict[str, Animation] = {}
        for name, record in _mapping(data["animations"], "Animations").items():
            if version == 1:
                if not isinstance(record, list):
                    raise ValueError("Legacy animation frames must be a list of paths.")
                animations[name] = Animation(
                    name, [_absolute_path(x, sage_directory) for x in cast(list[object], record)]
                )
            else:
                record = _mapping(record, "Animation metadata")
                if not isinstance(record.get("frames"), list):
                    raise ValueError("Animation metadata must contain a frames list.")
                frames = [
                    _mapping(x, "Animation frame") for x in cast(list[object], record["frames"])
                ]
                animations[name] = Animation(
                    name=name,
                    frames=[_absolute_path(x.get("path"), sage_directory) for x in frames],
                    fps=positive_number(record.get("fps", DEFAULT_ANIMATION_FPS), "Animation FPS"),
                    loop=record.get("loop", True),
                    frame_durations=[
                        positive_number(x.get("duration", 1.0), "Frame duration") for x in frames
                    ],
                    base_frame_duration=positive_number(
                        record.get("base_frame_duration", 1.0), "Base frame duration"
                    ),
                )
        return cls(
            uuid=data["uuid"],
            name=data["name"],
            description=data["description"],
            width=data["width"],
            height=data["height"],
            base_image=(
                "" if not data["base_image"] else _absolute_path(data["base_image"], sage_directory)
            ),
            animations=animations,
            include_base_image_in_animations=bool(
                data.get("include_base_image_in_animations", True)
            ),
            pixel_art=bool(data.get("pixel_art", True)),
        )

    @classmethod
    def from_json(cls, fpath: str, sage_directory: str) -> "SpriteFile":
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data=data, sage_directory=sage_directory)

    def save(self, fpath: str, sage_directory: str) -> None:
        save_document(fpath, self.to_dict(sage_directory=sage_directory))

    def to_dict(self, sage_directory: str) -> dict[str, object]:
        for animation in self.animations.values():
            animation.validate()
        return {
            "format_version": SPRITE_FORMAT_VERSION,
            "uuid": self.uuid,
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "base_image": (
                self.base_image
                if not self.base_image
                else os.path.relpath(self.base_image, sage_directory).replace("\\", "/")
            ),
            "include_base_image_in_animations": self.include_base_image_in_animations,
            "pixel_art": self.pixel_art,
            "animations": {
                name: {
                    "fps": animation.fps,
                    "loop": animation.loop,
                    "base_frame_duration": animation.base_frame_duration,
                    "frames": [
                        {
                            "path": os.path.relpath(path, sage_directory).replace("\\", "/"),
                            "duration": duration,
                        }
                        for path, duration in zip(
                            animation.frames, animation.frame_durations, strict=True
                        )
                    ],
                }
                for name, animation in self.animations.items()
            },
        }

    def get_animation_frames(self, animation_name: str) -> list[str]:
        if animation_name in self.animations.keys():
            return self.animations[animation_name].frames
        return []

    def get_animation_playback_frames(self, animation_name: str) -> list[str]:
        return self.get_animation_playback(animation_name).frames

    def get_animation_playback(self, animation_name: str) -> Animation:
        animation = self.animations.get(animation_name, Animation(animation_name, []))
        animation.validate()
        frames = list(animation.frames)
        durations = list(animation.frame_durations)
        if self.include_base_image_in_animations and self.base_image:
            frames.insert(0, self.base_image)
            durations.insert(0, animation.base_frame_duration)
        return Animation(animation.name, frames, animation.fps, animation.loop, durations)

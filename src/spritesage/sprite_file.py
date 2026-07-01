"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

# pyright: strict

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class Animation:
    name: str
    frames: list[str]


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

    @classmethod
    def from_dict(cls, data: dict[str, Any], sage_directory: str) -> "SpriteFile":
        animations: dict[str, Animation] = {}
        for animation in data["animations"].keys():
            animations[animation] = Animation(
                name=animation,
                frames=[os.path.join(sage_directory, x) for x in data["animations"][animation]],
            )
        return cls(
            uuid=data["uuid"],
            name=data["name"],
            description=data["description"],
            width=data["width"],
            height=data["height"],
            base_image=(
                "" if not data["base_image"] else os.path.join(sage_directory, data["base_image"])
            ),
            animations=animations,
            include_base_image_in_animations=bool(
                data.get("include_base_image_in_animations", True)
            ),
        )

    @classmethod
    def from_json(cls, fpath: str, sage_directory: str) -> "SpriteFile":
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data=data, sage_directory=sage_directory)

    def save(self, fpath: str, sage_directory: str) -> None:
        with open(fpath, "w", encoding="utf-8") as f:
            # Serialize current state to JSON
            json.dump(self.to_dict(sage_directory=sage_directory), f)

    def to_dict(self, sage_directory: str) -> dict[str, object]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "base_image": (
                self.base_image
                if not self.base_image
                else os.path.relpath(self.base_image, sage_directory)
            ),
            "include_base_image_in_animations": self.include_base_image_in_animations,
            "animations": {
                x: [os.path.relpath(y, sage_directory) for y in self.animations[x].frames]
                for x in self.animations.keys()
            },
        }

    def get_animation_frames(self, animation_name: str) -> list[str]:
        if animation_name in self.animations.keys():
            return self.animations[animation_name].frames
        return []

    def get_animation_playback_frames(self, animation_name: str) -> list[str]:
        frames = list(self.get_animation_frames(animation_name))
        if self.include_base_image_in_animations and self.base_image:
            return [self.base_image, *frames]
        return frames

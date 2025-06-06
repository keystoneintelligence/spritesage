"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class Animation:
    name: str
    frames: List[str]


@dataclass
class SpriteFile:
    uuid: str
    name: str
    description: str
    width: int
    height: int
    base_image: str
    animations: Dict[str, Animation]

    @classmethod
    def from_dict(cls, data: dict, sage_directory: str):
        animations: List[Animation] = {}
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
            base_image=None if not data["base_image"] else os.path.join(sage_directory, data["base_image"]),
            animations=animations,
        )
    
    @classmethod
    def from_json(cls, fpath: str, sage_directory: str):
        with open(fpath) as f:
            data = json.load(f)
        return cls.from_dict(data=data, sage_directory=sage_directory)
    
    def save(self, fpath: str, sage_directory: str):
        with open(fpath, "w") as f:
            # Serialize current state to JSON
            json.dump(self.to_dict(sage_directory=sage_directory), f)
    
    def to_dict(self, sage_directory: str) -> dict:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "base_image": self.base_image if not self.base_image else os.path.relpath(self.base_image, sage_directory),
            "animations": {x: [os.path.relpath(y, sage_directory) for y in self.animations[x].frames] for x in self.animations.keys()}
        }
    
    def get_animation_frames(self, animation_name: str) -> List[str]:
        if animation_name in self.animations.keys():
            return self.animations[animation_name].frames
        return []

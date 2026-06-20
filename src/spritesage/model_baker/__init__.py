"""
Stage-1 3D model to Sprite Sage asset baking.

The package API intentionally avoids importing the VTK renderer until a
bake is requested, so regular Sprite Sage startup stays isolated from renderer
initialization errors.
"""

from .service import (
    ModelAnimation,
    ModelBakeConfig,
    ModelBakeResult,
    available_view_sets,
    bake_model_to_sprite_project,
    inspect_model_animations,
)
from .sprite_writer import SpriteWriteResult, write_sprite_file_from_manifest

__all__ = [
    "ModelBakeConfig",
    "ModelBakeResult",
    "ModelAnimation",
    "SpriteWriteResult",
    "available_view_sets",
    "bake_model_to_sprite_project",
    "inspect_model_animations",
    "write_sprite_file_from_manifest",
]

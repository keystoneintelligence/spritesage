from __future__ import annotations

# pyright: strict

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast
import uuid

from spritesage.sprite_file import Animation, SpriteFile


@dataclass(frozen=True)
class SpriteWriteResult:
    sprite_path: Path
    animation_names: tuple[str, ...]
    base_image_path: Path
    frame_count: int


def write_sprite_file_from_manifest(
    manifest_path: str | Path,
    *,
    sprite_path: str | Path,
    project_dir: str | Path,
    sprite_name: str | None = None,
    description: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> SpriteWriteResult:
    """Create a Sprite Sage `.sprite` file from a model-baker manifest."""
    manifest_path = Path(manifest_path)
    sprite_path = Path(sprite_path)
    project_dir = Path(project_dir)

    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    sprite_width = int(width or manifest.get("size") or 256)
    sprite_height = int(height or manifest.get("size") or sprite_width)

    animations: dict[str, Animation] = {}
    total_frames = 0
    manifest_base_image = manifest.get("base_image")
    base_image_path = (
        _resolve_manifest_path(manifest_base_image, manifest_path.parent)
        if manifest_base_image
        else None
    )

    animation_records = manifest.get("animations")
    if not isinstance(animation_records, list):
        animation_records = []
    else:
        animation_records = cast(list[object], animation_records)

    for index, animation_data in enumerate(animation_records):
        if not isinstance(animation_data, dict):
            continue
        animation_record = cast(dict[str, object], animation_data)
        clip_name = str(animation_record.get("name") or f"animation_{index:02d}")
        views_value = animation_record.get("views")
        if not isinstance(views_value, dict):
            continue
        views = cast(dict[str, object], views_value)
        for view_name, frame_values in views.items():
            if not isinstance(frame_values, list):
                continue
            frame_values = cast(list[object], frame_values)
            frame_paths = [
                _resolve_manifest_path(str(frame_value), manifest_path.parent)
                for frame_value in frame_values
            ]
            if not frame_paths:
                continue

            animation_name = _unique_name(
                _safe_name(f"{clip_name}_{view_name}", fallback=f"animation_{index:02d}"),
                animations,
            )
            frames = [str(path) for path in frame_paths]
            animations[animation_name] = Animation(name=animation_name, frames=frames)
            total_frames += len(frames)
            if base_image_path is None:
                base_image_path = frame_paths[0]

    if not animations or base_image_path is None:
        raise ValueError(f"Bake manifest contains no sprite animation frames: {manifest_path}")

    sprite = SpriteFile(
        uuid=str(uuid.uuid4()),
        name=sprite_name or _default_sprite_name(manifest, sprite_path),
        description=description or _default_description(manifest),
        width=sprite_width,
        height=sprite_height,
        base_image=str(base_image_path),
        animations=animations,
        include_base_image_in_animations=False,
    )

    sprite_path.parent.mkdir(parents=True, exist_ok=True)
    sprite.save(str(sprite_path), str(project_dir))
    return SpriteWriteResult(
        sprite_path=sprite_path,
        animation_names=tuple(animations.keys()),
        base_image_path=base_image_path,
        frame_count=total_frames,
    )


def _resolve_manifest_path(value: str, manifest_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (manifest_dir / path).resolve()


def _default_sprite_name(manifest: dict[str, Any], sprite_path: Path) -> str:
    model_path = manifest.get("model")
    if model_path:
        return Path(str(model_path)).stem
    return sprite_path.stem


def _default_description(manifest: dict[str, Any]) -> str:
    model = Path(str(manifest.get("model") or "3D model")).name
    view_set = manifest.get("view_set", "unknown")
    fps = manifest.get("fps", "unknown")
    return f"Generated from {model} with {view_set} camera views at {fps} FPS."


def _safe_name(value: str, *, fallback: str = "animation") -> str:
    safe = "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in value)
    return safe.strip("_") or fallback


def _unique_name(name: str, existing: dict[str, Animation]) -> str:
    if name not in existing:
        return name

    suffix = 2
    while f"{name}_{suffix}" in existing:
        suffix += 1
    return f"{name}_{suffix}"

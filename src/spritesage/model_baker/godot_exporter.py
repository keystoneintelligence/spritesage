from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid


@dataclass(frozen=True)
class GodotExportResult:
    output_dir: Path
    sprite_frames_path: Path
    scene_path: Path


def export_godot_sprite(
    *,
    output_dir: str | Path,
    sprite_name: str,
    animations: list[dict],
    cell_size: int,
    fps: float,
) -> GodotExportResult:
    """Write Godot 4 SpriteFrames and AnimatedSprite2D files for a bake.

    Each baked source animation is expanded into one Godot animation per camera
    view. For example, `Walking` with an `iso4` view set becomes
    `Walking_front_right`, `Walking_back_right`, `Walking_back_left`, and
    `Walking_front_left`.
    """
    godot_dir = Path(output_dir) / "godot"
    godot_dir.mkdir(parents=True, exist_ok=True)

    safe_sprite_name = _safe_name(sprite_name)
    tres_uid = _uid()
    scene_uid = _uid()
    tres_path = godot_dir / f"{safe_sprite_name}_frames.tres"
    scene_path = godot_dir / f"{safe_sprite_name}.tscn"

    ext_resources: list[tuple[str, str, Path]] = []
    atlas_resources: list[tuple[str, str, int, int, int, int]] = []
    godot_animations: list[dict] = []

    for sheet_index, animation in enumerate(animations, start=1):
        ext_id = str(sheet_index)
        sheet_path = Path(animation["sheet"])
        ext_resources.append((ext_id, _uid(), sheet_path))

        views = animation["views"]
        frame_count = len(animation["times"])
        for row_index, view_name in enumerate(views.keys()):
            godot_animation_name = _safe_name(f"{animation['name']}_{view_name}")
            frame_refs: list[str] = []
            for frame_index in range(frame_count):
                sub_id = _safe_resource_id(f"AtlasTexture_{godot_animation_name}_{frame_index:03d}")
                x = frame_index * cell_size
                y = row_index * cell_size
                atlas_resources.append((sub_id, ext_id, x, y, cell_size, cell_size))
                frame_refs.append(sub_id)
            godot_animations.append(
                {
                    "name": godot_animation_name,
                    "frames": frame_refs,
                    "speed": float(fps),
                    "loop": _should_loop(animation["name"]),
                }
            )

    load_steps = 1 + len(ext_resources) + len(atlas_resources)
    _write_tres(
        path=tres_path,
        uid=tres_uid,
        load_steps=load_steps,
        ext_resources=ext_resources,
        atlas_resources=atlas_resources,
        animations=godot_animations,
        base_dir=godot_dir,
    )
    _write_tscn(
        path=scene_path,
        uid=scene_uid,
        sprite_frames_uid=tres_uid,
        sprite_frames_path=tres_path,
        node_name=safe_sprite_name,
        default_animation=godot_animations[0]["name"] if godot_animations else "",
    )
    return GodotExportResult(
        output_dir=godot_dir,
        sprite_frames_path=tres_path,
        scene_path=scene_path,
    )


def _write_tres(
    *,
    path: Path,
    uid: str,
    load_steps: int,
    ext_resources: list[tuple[str, str, Path]],
    atlas_resources: list[tuple[str, str, int, int, int, int]],
    animations: list[dict],
    base_dir: Path,
) -> None:
    with path.open("w", encoding="utf-8") as tres:
        tres.write(
            f'[gd_resource type="SpriteFrames" load_steps={load_steps} format=3 uid="{uid}"]\n\n'
        )

        for ext_id, texture_uid, sheet_path in ext_resources:
            tres.write(
                f'[ext_resource type="Texture2D" uid="{texture_uid}" '
                f'path="{_godot_rel_path(sheet_path, base_dir)}" id="{ext_id}"]\n'
            )
        tres.write("\n")

        for sub_id, ext_id, x, y, width, height in atlas_resources:
            tres.write(f'[sub_resource type="AtlasTexture" id="{sub_id}"]\n')
            tres.write(f'atlas = ExtResource("{ext_id}")\n')
            tres.write(f"region = Rect2({x}, {y}, {width}, {height})\n\n")

        tres.write("[resource]\n")
        tres.write("animations = [\n")
        for animation in animations:
            tres.write("  {\n")
            tres.write('    "frames": [\n')
            for sub_id in animation["frames"]:
                tres.write("      {\n")
                tres.write('        "duration": 1.0,\n')
                tres.write(f'        "texture": SubResource("{sub_id}")\n')
                tres.write("      },\n")
            tres.write("    ],\n")
            tres.write(f'    "loop": {str(animation["loop"]).lower()},\n')
            tres.write(f'    "name": &"{animation["name"]}",\n')
            tres.write(f'    "speed": {animation["speed"]:.6g}\n')
            tres.write("  },\n")
        tres.write("]\n")


def _write_tscn(
    *,
    path: Path,
    uid: str,
    sprite_frames_uid: str,
    sprite_frames_path: Path,
    node_name: str,
    default_animation: str,
) -> None:
    with path.open("w", encoding="utf-8") as tscn:
        tscn.write(f'[gd_scene load_steps=2 format=3 uid="{uid}"]\n\n')
        tscn.write(
            f'[ext_resource type="SpriteFrames" uid="{sprite_frames_uid}" '
            f'path="{sprite_frames_path.name}" id="1"]\n\n'
        )
        tscn.write(f'[node name="{node_name}" type="AnimatedSprite2D"]\n')
        tscn.write('sprite_frames = ExtResource("1")\n')
        if default_animation:
            tscn.write(f'animation = &"{default_animation}"\n')


def _godot_rel_path(path: Path, base_dir: Path) -> str:
    try:
        rel = path.resolve().relative_to(base_dir.resolve())
    except ValueError:
        rel = Path("..") / path.resolve().relative_to(base_dir.resolve().parent)
    return rel.as_posix()


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in value)
    return safe or "sprite"


def _safe_resource_id(value: str) -> str:
    return _safe_name(value)[:120]


def _should_loop(animation_name: str) -> bool:
    return animation_name.lower() not in {"dead", "death", "die", "dying"}


def _uid() -> str:
    return f"uid://{uuid.uuid4().hex[:12]}"

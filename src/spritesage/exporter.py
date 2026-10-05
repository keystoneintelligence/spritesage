"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import uuid
import json
from pathlib import Path
from typing import Callable
from .sprite_file import SpriteFile
from .spritesheet import SpriteSheetGenerator
from PIL import Image
from .godot_preservation import prepare_export
from .godot_export_transaction import ExportPlan, recover_pending_export
from .paths import safe_asset_name

ProgressCallback = Callable[..., None]


class GodotSpriteExporter:
    """
    Reads a .sprite JSON, builds a spritesheet via SpriteSheetGenerator,
    and writes out a Godot 4 SpriteFrames .tres resource.
    """

    def __init__(
        self,
        sprite_file: SpriteFile,
        output_dir: str = ".",
        progress_callback: ProgressCallback | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.sprite_file = sprite_file
        self.asset_name = safe_asset_name(sprite_file.name)
        self.progress_callback = progress_callback

        # Instantiate your generator
        self.sheet_gen = SpriteSheetGenerator(sprite_file=self.sprite_file)
        self.frame_paths = self.sheet_gen.get_all_frame_paths()
        self.frame_count = len(self.frame_paths)

    def prepare(self) -> ExportPlan:
        return prepare_export(self)

    def export(self):
        return self.prepare().apply()

    def _write_new_export(self):
        if self.frame_count == 0:
            self._write_new_sprite2d()
        else:
            self._write_new_tres()

    def _write_new_tres(self):
        # 1) Create the sheet PNG
        sheet_png = self.sheet_gen.create_spritesheet(
            output_path=str(self.output_dir / f"{self.asset_name}_sheet.png"),
            progress_callback=self.progress_callback,
            extract_alpha=False,
        )

        # 2) Compute layout
        w, h = self.sheet_gen.width, self.sheet_gen.height
        sheet_size = self.sheet_gen.determine_sheet_size(self.frame_count)
        cols = sheet_size // w

        # 3) Prepare UIDs
        tres_uid = f"uid://{uuid.uuid4().hex[:12]}"
        ext_res_id = "1"
        sub_ids = [f"AtlasTexture_{uuid.uuid4().hex[:6]}" for _ in range(self.frame_count)]

        # 4) Open .tres for writing
        tres_path = self.output_dir / f"{self.asset_name}_frames.tres"
        with open(tres_path, "w", encoding="utf-8") as tres:
            # Header
            tres.write(
                f'[gd_resource type="SpriteFrames" load_steps={self.frame_count + 2} format=3 uid="{tres_uid}"]\n\n'
            )

            sheet_path = Path(sheet_png)
            try:
                rel = sheet_path.relative_to(self.output_dir)
                godot_path = f"{rel.as_posix()}"
            except ValueError:
                godot_path = sheet_path.as_posix().replace("\\", "/")
            tres.write(
                '[ext_resource type="Texture2D" ' f'path="{godot_path}" id="{ext_res_id}"]\n\n'
            )

            # Subresources: one AtlasTexture per frame
            for idx, sub_id in enumerate(sub_ids):
                x = (idx % cols) * w
                y = (idx // cols) * h
                tres.write(f'[sub_resource type="AtlasTexture" id="{sub_id}"]\n')
                tres.write(f'atlas = ExtResource("{ext_res_id}")\n')
                tres.write(f"region = Rect2({x}, {y}, {w}, {h})\n\n")

            # Resource block: animations array (JSON-style keys)
            tres.write("[resource]\n")
            tres.write("animations = [\n")

            frame_idx = 0
            for anim_name in sorted(self.sprite_file.animations.keys()):
                animation = self.sprite_file.get_animation_playback(anim_name)
                tres.write("  {\n")
                tres.write('    "frames": [\n')
                for duration in animation.frame_durations:
                    sub_id = sub_ids[frame_idx]
                    tres.write("      {\n")
                    tres.write(f'        "duration": {duration:.12g},\n')
                    tres.write(f'        "texture": SubResource("{sub_id}")\n')
                    tres.write("      },\n")
                    frame_idx += 1
                tres.write("    ],\n")
                tres.write(f'    "loop": {str(animation.loop).lower()},\n')
                tres.write(f'    "name": &{json.dumps(anim_name, ensure_ascii=False)},\n')
                tres.write(f'    "speed": {animation.fps:.12g}\n')
                tres.write("  },\n")
            tres.write("]\n")

        # keep the SpriteFrames UID around for the .tscn
        self.tres_uid = tres_uid

        # now also dump a .tscn
        self._write_new_tscn()

    def _write_new_tscn(self):
        # generate a new UID for the scene
        tscn_uid = f"uid://{uuid.uuid4().hex[:12]}"

        # make a fresh ext_resource id (so it's unique)
        scene_ext_id = f"1_{uuid.uuid4().hex[:6]}"

        # names & defaults
        name = self.asset_name
        tres_file = f"{name}_frames.tres"
        # pick the first animation as default
        default_anim = next(iter(self.sprite_file.animations.keys()))

        tscn_path = self.output_dir / f"{name}.tscn"
        with open(tscn_path, "w", encoding="utf-8") as tscn:
            tscn.write(f'[gd_scene load_steps=2 format=3 uid="{tscn_uid}"]\n\n')
            tscn.write(
                f'[ext_resource type="SpriteFrames" '
                f'uid="{self.tres_uid}" '
                f'path="{tres_file}" '
                f'id="{scene_ext_id}"]\n\n'
            )
            tscn.write(f'[node name="{name}" type="AnimatedSprite2D"]\n')
            tscn.write(f"texture_filter = {1 if self.sprite_file.pixel_art else 2}\n")
            tscn.write(f'sprite_frames = ExtResource("{scene_ext_id}")\n')
            tscn.write(f"animation = &{json.dumps(default_anim, ensure_ascii=False)}\n")

    def _write_new_sprite2d(self):
        name = self.asset_name
        # copy base image into output folder
        if not self.sprite_file.base_image:
            raise ValueError("Cannot export a static sprite without a base image.")
        src = Path(self.sprite_file.base_image)
        dst = self.output_dir / f"{name}.png"
        with Image.open(src) as image:
            image.convert("RGBA").save(dst, format="PNG")

        # Prepare a scene UID; Godot owns imported texture UIDs.
        tscn_uid = f"uid://{uuid.uuid4().hex[:12]}"
        ext_id = "1"

        # write a minimal .tscn for Sprite2D
        tscn_path = self.output_dir / f"{name}.tscn"
        with open(tscn_path, "w", encoding="utf-8") as f:
            f.write(f'[gd_scene load_steps=2 format=3 uid="{tscn_uid}"]\n\n')
            f.write('[ext_resource type="Texture2D" ' f'path="{dst.name}" ' f'id="{ext_id}"]\n\n')
            f.write(f'[node name="{name}" type="Sprite2D"]\n')
            f.write(f"texture_filter = {1 if self.sprite_file.pixel_art else 2}\n")
            f.write(f'texture = ExtResource("{ext_id}")\n')


class GodotProjectExporter:
    """Exports every .sprite file in a Sprite Sage project for Godot 4."""

    def __init__(
        self,
        project_dir: str,
        output_dir: str,
        progress_callback: ProgressCallback | None = None,
        hidden_sprites: list[str] | None = None,
    ):
        self.project_dir = Path(project_dir)
        self.output_dir = Path(output_dir)
        self.progress_callback = progress_callback
        self.hidden_sprites = {path.replace("\\", "/") for path in hidden_sprites or []}

    def _sprite_paths(self) -> list[Path]:
        return sorted(
            path
            for path in self.project_dir.rglob("*.sprite")
            if path.is_file()
            and not self._is_inside_output_dir(path)
            and path.relative_to(self.project_dir).as_posix() not in self.hidden_sprites
        )

    def _is_inside_output_dir(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.output_dir.resolve())
            return True
        except ValueError:
            return False

    def _report_progress(self, current: int, total: int, detail: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(current, total, detail)
        except TypeError:
            self.progress_callback(current, total)

    def export(self) -> list[Path]:
        return self.prepare().apply()

    def prepare(self) -> ExportPlan:
        recover_pending_export(self.output_dir)
        sprite_paths = self._sprite_paths()
        if not sprite_paths:
            raise ValueError("No .sprite files were found in this project.")

        plan = ExportPlan(root=self.output_dir)
        total = len(sprite_paths)
        self._report_progress(0, total, f"Preparing {total} sprites for Godot export")

        for index, sprite_path in enumerate(sprite_paths, start=1):
            relative_path = sprite_path.relative_to(self.project_dir)
            relative_label = relative_path.as_posix()
            sprite_output_dir = self.output_dir / relative_path.with_suffix("")
            self._report_progress(index - 1, total, f"Exporting {relative_label}")

            plan.guards[sprite_path] = sprite_path.read_bytes()
            sprite_file = SpriteFile.from_json(
                fpath=str(sprite_path),
                sage_directory=str(self.project_dir),
            )

            def report_sprite_progress(
                frame_current: int,
                frame_total: int,
                frame_detail: str = "",
                sprite_label: str = relative_label,
                progress_index: int = index - 1,
            ) -> None:
                detail = frame_detail or "Processing sprite"
                if frame_total > 0:
                    detail = (
                        f"Exporting {sprite_label}: {detail} "
                        f"({frame_current} of {frame_total} frames)"
                    )
                else:
                    detail = f"Exporting {sprite_label}: {detail}"
                self._report_progress(progress_index, total, detail)

            sprite_exporter = GodotSpriteExporter(
                sprite_file=sprite_file,
                output_dir=str(sprite_output_dir),
                progress_callback=report_sprite_progress,
            )
            sprite_plan = sprite_exporter.prepare()
            for field in ("updates", "creations", "conflicts"):
                setattr(
                    sprite_plan,
                    field,
                    [f"{relative_label}: {value}" for value in getattr(sprite_plan, field)],
                )
            plan.merge(sprite_plan)
            self._report_progress(index, total, f"Prepared {relative_label}")

        return plan

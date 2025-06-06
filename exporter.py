"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import uuid
from pathlib import Path
from sprite_file import SpriteFile
from spritesheet import SpriteSheetGenerator
from utils import remove_background

class GodotSpriteExporter:
    """
    Reads a .sprite JSON, builds a spritesheet via SpriteSheetGenerator,
    and writes out a Godot 4 SpriteFrames .tres resource.
    """
    def __init__(self, sprite_file: SpriteFile, output_dir: str = "."):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sprite_file = sprite_file

        # Instantiate your generator
        self.sheet_gen = SpriteSheetGenerator(sprite_file=self.sprite_file)
        self.frame_paths = self.sheet_gen.get_all_frame_paths()
        self.frame_count = len(self.frame_paths)

    def export(self):
        if self.frame_count == 0:
            self.export_sprite2d()
        else:
            self.export_tres()

    def export_tres(self):
        # 1) Create the sheet PNG
        sheet_png = self.sheet_gen.create_spritesheet(
            output_path=str(self.output_dir / f"{self.sprite_file.name}_sheet.png")
        )

        # 2) Compute layout
        w, h = self.sheet_gen.width, self.sheet_gen.height
        sheet_size = self.sheet_gen.determine_sheet_size(self.frame_count)
        cols = sheet_size // w

        # 3) Prepare UIDs
        tres_uid       = f"uid://{uuid.uuid4().hex[:12]}"
        texture_uid    = f"uid://{uuid.uuid4().hex[:12]}"
        ext_res_id     = "1"
        sub_ids = [f"AtlasTexture_{uuid.uuid4().hex[:6]}" for _ in range(self.frame_count)]

        # 4) Open .tres for writing
        tres_path = self.output_dir / f"{self.sprite_file.name}_frames.tres"
        with open(tres_path, 'w') as tres:
            # Header
            tres.write(f'[gd_resource type="SpriteFrames" load_steps=1 format=3 uid="{tres_uid}"]\n\n')

            sheet_path = Path(sheet_png)
            try:
                rel = sheet_path.relative_to(self.output_dir)
                godot_path = f"{rel.as_posix()}"
            except ValueError:
                godot_path = sheet_path.as_posix().replace("\\", "/")
            tres.write(
                f'[ext_resource type="Texture2D" uid="{texture_uid}" '
                f'path="{godot_path}" id="{ext_res_id}"]\n\n'
            )

            # Subresources: one AtlasTexture per frame
            for idx, sub_id in enumerate(sub_ids):
                x = (idx % cols) * w
                y = (idx // cols) * h
                tres.write(f'[sub_resource type="AtlasTexture" id="{sub_id}"]\n')
                tres.write(f'atlas = ExtResource("{ext_res_id}")\n')
                tres.write(f'region = Rect2({x}, {y}, {w}, {h})\n\n')

            # Resource block: animations array (JSON-style keys)
            tres.write('[resource]\n')
            tres.write('animations = [\n')

            frame_idx = 0
            for anim_name in sorted(self.sprite_file.animations.keys()):
                frames = self.sprite_file.get_animation_frames(anim_name)
                tres.write('  {\n')
                tres.write('    "frames": [\n')
                for _ in frames:
                    sub_id = sub_ids[frame_idx]
                    tres.write('      {\n')
                    tres.write('        "duration": 1.0,\n')
                    tres.write(f'        "texture": SubResource("{sub_id}")\n')
                    tres.write('      },\n')
                    frame_idx += 1
                tres.write('    ],\n')
                tres.write('    "loop": true,\n')
                tres.write(f'    "name": &"{anim_name}",\n')
                tres.write('    "speed": 1.0\n')
                tres.write('  },\n')
            tres.write(']\n')

        # keep the SpriteFrames UID around for the .tscn
        self.tres_uid = tres_uid

        # now also dump a .tscn
        self.export_tscn()

    def export_tscn(self):
        # generate a new UID for the scene
        tscn_uid = f"uid://{uuid.uuid4().hex[:12]}"

        # make a fresh ext_resource id (so it's unique)
        scene_ext_id = f"1_{uuid.uuid4().hex[:6]}"

        # names & defaults
        name       = self.sprite_file.name
        tres_file  = f"{name}_frames.tres"
        # pick the first animation as default
        default_anim = next(iter(self.sprite_file.animations.keys()))

        tscn_path = self.output_dir / f"{name}.tscn"
        with open(tscn_path, 'w') as tscn:
            tscn.write(f'[gd_scene load_steps=2 format=3 uid="{tscn_uid}"]\n\n')
            tscn.write(
                f'[ext_resource type="SpriteFrames" '
                f'uid="{self.tres_uid}" '
                f'path="{tres_file}" '
                f'id="{scene_ext_id}"]\n\n'
            )
            tscn.write(f'[node name="{name}" type="AnimatedSprite2D"]\n')
            tscn.write(f'sprite_frames = ExtResource("{scene_ext_id}")\n')
            tscn.write(f'animation = &"{default_anim}"\n')

    def export_sprite2d(self):
        name = self.sprite_file.name
        # copy base image into output folder
        src = Path(self.sprite_file.base_image)
        dst = self.output_dir / src.name
        remove_background(src, dst)

        # prepare UIDs for scene and texture
        tscn_uid = f"uid://{uuid.uuid4().hex[:12]}"
        tex_uid  = f"uid://{uuid.uuid4().hex[:12]}"
        ext_id   = "1"

        # write a minimal .tscn for Sprite2D
        tscn_path = self.output_dir / f"{name}.tscn"
        with open(tscn_path, 'w') as f:
            f.write(f'[gd_scene load_steps=2 format=3 uid="{tscn_uid}"]\n\n')
            f.write(
                f'[ext_resource type="Texture2D" '
                f'uid="{tex_uid}" '
                f'path="{dst.name}" '
                f'id="{ext_id}"]\n\n'
            )
            f.write(f'[node name="{name}" type="Sprite2D"]\n')
            f.write(f'texture = ExtResource("{ext_id}")\n')

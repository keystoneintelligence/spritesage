from __future__ import annotations

import argparse
from pathlib import Path

from .cameras import VIEW_SETS
from .service import ModelBakeConfig, bake_model_to_sprite_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bake an animated GLB model into a Sprite Sage project asset."
    )
    parser.add_argument("--model", type=Path, required=True, help="Path to the source .glb model")
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Sprite Sage project directory where the .sprite file should be written",
    )
    parser.add_argument("--sprite-name", help="Output sprite name; defaults to the model stem")
    parser.add_argument(
        "--output-subdir",
        type=Path,
        help="Project-relative output directory; defaults to sprites/<sprite-name>",
    )
    parser.add_argument("--view-set", choices=sorted(VIEW_SETS), default="iso8")
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--size", type=int, default=256, help="Square frame size in pixels")
    parser.add_argument("--zoom", type=float, default=1.0)
    parser.add_argument("--style", choices=("none", "pixel"), default="none")
    parser.add_argument("--pixel-size", type=int, default=4)
    parser.add_argument("--animation", action="append", dest="animations")
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-copy-source-model", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = bake_model_to_sprite_project(
        ModelBakeConfig(
            model_path=args.model,
            project_dir=args.project_dir,
            sprite_name=args.sprite_name,
            output_subdir=args.output_subdir,
            view_set=args.view_set,
            fps=args.fps,
            frame_size=args.size,
            zoom=args.zoom,
            style=args.style,
            pixel_size=args.pixel_size,
            selected_animations=args.animations,
            max_frames=args.max_frames,
            copy_source_model=not args.no_copy_source_model,
            overwrite=args.overwrite,
        )
    )
    print(f"Sprite: {result.sprite_path}")
    print(f"Frames: {result.frame_count}")
    print(f"Manifest: {result.manifest_path}")
    print(f"Output: {result.bake_output_dir}")
    if result.source_model_path:
        print(f"Source model copy: {result.source_model_path}")
    for sheet_path in result.sheet_paths:
        print(f"Sheet: {sheet_path}")
    if result.godot_sprite_frames_path:
        print(f"Godot SpriteFrames: {result.godot_sprite_frames_path}")
    if result.godot_scene_path:
        print(f"Godot Scene: {result.godot_scene_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
import os
from pathlib import Path

import pytest

from spritesage.model_baker import (
    ModelBakeConfig,
    available_view_sets,
    bake_model_to_sprite_project,
    write_sprite_file_from_manifest,
)
from spritesage.model_baker.animations import AnimationClip, select_base_pose_clip
from spritesage.sprite_file import SpriteFile


def test_available_view_sets_exposes_prototype_camera_presets():
    assert {"front3", "side2", "iso4", "iso8", "top"}.issubset(set(available_view_sets()))


def test_base_pose_selection_prefers_idle_then_walking():
    walking = AnimationClip(index=1, name="Walking", duration=1.0)
    idle = AnimationClip(index=2, name="Combat Idle", duration=2.0)
    running = AnimationClip(index=3, name="Running", duration=1.0)

    assert select_base_pose_clip([running, walking, idle]) == idle
    assert select_base_pose_clip([running, walking]) == walking
    assert select_base_pose_clip([running]) is None


def test_write_sprite_file_from_manifest_creates_project_relative_sprite(tmp_path):
    project_dir = tmp_path / "project"
    bake_dir = project_dir / "sprites" / "bandit"
    frame_a = bake_dir / "frames" / "Walking" / "front_right" / "frame_000.png"
    frame_b = bake_dir / "frames" / "Walking" / "front_right" / "frame_001.png"
    frame_c = bake_dir / "frames" / "Walking" / "back" / "frame_000.png"
    base_frame = bake_dir / "base" / "front.png"
    for frame in (base_frame, frame_a, frame_b, frame_c):
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"placeholder")

    manifest_path = bake_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "model": "bandit.glb",
                "view_set": "iso8",
                "fps": 8.0,
                "size": 128,
                "base_image": "base/front.png",
                "animations": [
                    {
                        "name": "Walking",
                        "views": {
                            "front_right": [
                                "frames/Walking/front_right/frame_000.png",
                                "frames/Walking/front_right/frame_001.png",
                            ],
                            "back": ["frames/Walking/back/frame_000.png"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sprite_path = project_dir / "bandit.sprite"
    result = write_sprite_file_from_manifest(
        manifest_path,
        sprite_path=sprite_path,
        project_dir=project_dir,
        sprite_name="Bandit",
    )

    data = json.loads(sprite_path.read_text(encoding="utf-8"))
    assert data["name"] == "Bandit"
    assert data["width"] == 128
    assert data["height"] == 128
    assert os.path.normpath(data["base_image"]) == os.path.normpath("sprites/bandit/base/front.png")
    assert data["include_base_image_in_animations"] is False
    assert data["animations"] == {
        "Walking_front_right": [
            os.path.normpath("sprites/bandit/frames/Walking/front_right/frame_000.png"),
            os.path.normpath("sprites/bandit/frames/Walking/front_right/frame_001.png"),
        ],
        "Walking_back": [
            os.path.normpath("sprites/bandit/frames/Walking/back/frame_000.png"),
        ],
    }
    assert result.animation_names == ("Walking_front_right", "Walking_back")
    assert result.frame_count == 3

    loaded = SpriteFile.from_json(str(sprite_path), str(project_dir))
    assert loaded.name == "Bandit"
    assert Path(loaded.base_image) == base_frame
    assert loaded.get_animation_frames("Walking_front_right") == [str(frame_a), str(frame_b)]
    assert loaded.get_animation_playback_frames("Walking_front_right") == [
        str(frame_a),
        str(frame_b),
    ]


def test_write_sprite_file_from_manifest_rejects_empty_animation_data(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"animations": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="no sprite animation frames"):
        write_sprite_file_from_manifest(
            manifest_path,
            sprite_path=tmp_path / "empty.sprite",
            project_dir=tmp_path,
        )


def test_bake_model_to_sprite_project_rejects_non_glb_before_renderer_import(tmp_path):
    model_path = tmp_path / "bandit.obj"
    model_path.write_text("not a glb", encoding="utf-8")

    with pytest.raises(ValueError, match="supports .glb"):
        bake_model_to_sprite_project(
            ModelBakeConfig(model_path=model_path, project_dir=tmp_path / "project")
        )


def test_bake_model_to_sprite_project_refuses_existing_output_without_overwrite(tmp_path):
    model_path = tmp_path / "bandit.glb"
    model_path.write_bytes(b"placeholder")
    project_dir = tmp_path / "project"
    output_dir = project_dir / "sprites" / "Bandit"
    output_dir.mkdir(parents=True)
    (output_dir / "existing.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Bake output directory already has files"):
        bake_model_to_sprite_project(
            ModelBakeConfig(
                model_path=model_path,
                project_dir=project_dir,
                sprite_name="Bandit",
            )
        )


def test_bake_model_to_sprite_project_keeps_output_inside_project(tmp_path):
    model_path = tmp_path / "bandit.glb"
    model_path.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="inside the project directory"):
        bake_model_to_sprite_project(
            ModelBakeConfig(
                model_path=model_path,
                project_dir=tmp_path / "project",
                output_subdir=Path("..") / "outside",
            )
        )

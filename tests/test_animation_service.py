import os

import pytest

from spritesage.animation_service import (
    add_animation,
    insert_frames,
    move_frame,
    plan_ai_frame_after,
    plan_ai_frame_before,
    plan_frame_copy,
    remove_animation,
    remove_frames,
)
from spritesage.sprite_file import Animation, SpriteFile


def _sprite(frames: list[str] | None = None) -> SpriteFile:
    animations = {"idle": Animation(name="idle", frames=list(frames or []))}
    return SpriteFile(
        uuid="sprite-1",
        name="Hero",
        description="",
        width=32,
        height=32,
        base_image="base.png",
        animations=animations,
    )


def test_add_and_remove_animation_mutates_sprite_data():
    sprite = _sprite()

    add_animation(sprite, "walk")
    assert sprite.animations["walk"].frames == []

    with pytest.raises(ValueError):
        add_animation(sprite, "walk")

    assert remove_animation(sprite, "walk") is True
    assert "walk" not in sprite.animations
    assert remove_animation(sprite, "missing") is False


def test_plan_frame_copy_keeps_project_local_paths(tmp_path):
    base_dir = tmp_path / "project"
    base_dir.mkdir()
    frame_path = base_dir / "frame.png"

    plan = plan_frame_copy(str(frame_path), str(base_dir))

    assert plan.source_path == os.path.abspath(frame_path)
    assert plan.stored_path == os.path.abspath(frame_path)
    assert plan.requires_copy is False


def test_plan_frame_copy_chooses_unique_project_target(tmp_path):
    base_dir = tmp_path / "project"
    base_dir.mkdir()
    source_path = tmp_path / "imports" / "frame.png"
    occupied = {
        os.path.join(str(base_dir), "frame.png"),
        os.path.join(str(base_dir), "frame_1.png"),
    }

    plan = plan_frame_copy(str(source_path), str(base_dir), path_exists=occupied.__contains__)

    assert plan.source_path == os.path.abspath(source_path)
    assert plan.stored_path == os.path.normpath(os.path.join(str(base_dir), "frame_2.png"))
    assert plan.requires_copy is True


def test_insert_frames_clamps_index_and_skips_duplicates():
    sprite = _sprite(["a.png", "c.png"])

    inserted = insert_frames(sprite, "idle", 1, ["b.png", "a.png", "d.png"])

    assert [(frame.index, frame.path) for frame in inserted] == [
        (1, "b.png"),
        (2, "d.png"),
    ]
    assert sprite.get_animation_frames("idle") == ["a.png", "b.png", "d.png", "c.png"]


def test_remove_frames_removes_matching_paths():
    sprite = _sprite(["a.png", "b.png", "c.png", "b.png"])

    removed_count = remove_frames(sprite, "idle", ["b.png"])

    assert removed_count == 2
    assert sprite.get_animation_frames("idle") == ["a.png", "c.png"]
    assert remove_frames(sprite, "missing", ["a.png"]) == 0


def test_move_frame_reorders_with_bounds_checks():
    sprite = _sprite(["a.png", "b.png", "c.png"])

    assert move_frame(sprite, "idle", 1, -1) == 0
    assert sprite.get_animation_frames("idle") == ["b.png", "a.png", "c.png"]
    assert move_frame(sprite, "idle", 2, 1) is None
    assert sprite.get_animation_frames("idle") == ["b.png", "a.png", "c.png"]


def test_ai_frame_before_plans_empty_start_and_between_images():
    empty_sprite = _sprite([])
    assert plan_ai_frame_before(empty_sprite, "idle", 0).generation_kind == "next"
    assert plan_ai_frame_before(empty_sprite, "idle", 0).images == ("base.png",)

    sprite = _sprite(["a.png", "b.png", "c.png"])

    first_plan = plan_ai_frame_before(sprite, "idle", 0)
    assert first_plan.insertion_index == 0
    assert first_plan.generation_kind == "between"
    assert first_plan.images == ("base.png", "a.png")

    middle_plan = plan_ai_frame_before(sprite, "idle", 2)
    assert middle_plan.insertion_index == 2
    assert middle_plan.images == ("b.png", "c.png")


def test_ai_frame_after_plans_empty_end_and_between_images():
    empty_sprite = _sprite([])
    assert plan_ai_frame_after(empty_sprite, "idle", 0).generation_kind == "next"
    assert plan_ai_frame_after(empty_sprite, "idle", 0).insertion_index == 0

    sprite = _sprite(["a.png", "b.png", "c.png"])

    middle_plan = plan_ai_frame_after(sprite, "idle", 1)
    assert middle_plan.insertion_index == 2
    assert middle_plan.generation_kind == "between"
    assert middle_plan.images == ("b.png", "c.png")

    last_plan = plan_ai_frame_after(sprite, "idle", 2)
    assert last_plan.insertion_index == 3
    assert last_plan.images == ("c.png", "base.png")

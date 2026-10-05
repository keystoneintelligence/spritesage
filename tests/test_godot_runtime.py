"""Real Godot round trip. CI uses 4.4.1; set SPRITESAGE_GODOT locally."""

import os
import shutil
import subprocess

import pytest
from PIL import Image

from spritesage.exporter import GodotSpriteExporter
from spritesage.sprite_file import Animation, SpriteFile

GODOT = os.environ.get("SPRITESAGE_GODOT") or shutil.which("godot") or shutil.which("godot4")
pytestmark = pytest.mark.skipif(not GODOT, reason="Set SPRITESAGE_GODOT to run real engine tests")


def run_godot(project, *arguments):
    process = subprocess.run(
        [GODOT, "--headless", "--path", str(project), *arguments],
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = process.stdout + process.stderr
    assert process.returncode == 0, output
    assert "SCRIPT ERROR" not in output and "ERROR:" not in output, output
    return output


def test_godot_saves_tuning_then_loads_revised_art_with_gameplay_intact(tmp_path):
    (tmp_path / "project.godot").write_text(
        'config_version=5\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
        encoding="utf-8",
    )
    frames = []
    for index in range(6):
        path = tmp_path / f"frame-{index}.png"
        image = Image.new("RGBA", (8, 8))
        image.putpixel((index, 1), (index * 30, 80, 150, 128))
        image.save(path)
        frames.append(str(path))
    sprite = SpriteFile(
        "runtime-hero",
        "Hero",
        "",
        8,
        8,
        "",
        {"attack": Animation("attack", frames, 10, True)},
        include_base_image_in_animations=False,
    )
    output = tmp_path / "assets"
    exporter = GodotSpriteExporter(sprite, str(output))
    exporter.export()
    (tmp_path / "actor.gd").write_text(
        'extends AnimatedSprite2D\nfunc strike():\n    set_meta("hits", get_meta("hits", 0) + 1)\n',
        encoding="utf-8",
    )
    (tmp_path / "customize.gd").write_text(
        """extends SceneTree
func _initialize():
    var scene = load("res://assets/Hero.tscn").instantiate()
    scene.set_script(load("res://actor.gd"))
    scene.set_meta("health", 100)
    var frames = scene.sprite_frames
    frames.set_animation_speed("attack", 8.0)
    frames.set_animation_loop("attack", false)
    frames.set_frame("attack", 3, frames.get_frame_texture("attack", 3), 3.5)
    frames.set_meta("frame_event", {"attack:3": "strike"})
    assert(ResourceSaver.save(frames, "res://assets/Hero_frames.tres") == OK)
    var hitbox = Area2D.new()
    hitbox.name = "Hitbox"
    hitbox.collision_layer = 2
    hitbox.collision_mask = 4
    scene.add_child(hitbox)
    hitbox.owner = scene
    var shape = CollisionShape2D.new()
    shape.name = "Shape"
    shape.shape = RectangleShape2D.new()
    shape.shape.size = Vector2(6, 9)
    hitbox.add_child(shape)
    shape.owner = scene
    var player = AnimationPlayer.new()
    player.name = "Events"
    scene.add_child(player)
    player.owner = scene
    var animation = Animation.new()
    animation.length = 1.0
    var track = animation.add_track(Animation.TYPE_METHOD)
    animation.track_set_path(track, NodePath("."))
    animation.track_insert_key(track, 0.25, {"method": "strike", "args": []})
    var library = AnimationLibrary.new()
    library.add_animation("attack-events", animation)
    player.add_animation_library("", library)
    var packed = PackedScene.new()
    assert(packed.pack(scene) == OK)
    assert(ResourceSaver.save(packed, "res://assets/Hero.tscn") == OK)
    scene.free()
    print("CUSTOMIZED")
    quit()
""",
        encoding="utf-8",
    )
    run_godot(tmp_path, "--editor", "--import")
    assert "CUSTOMIZED" in run_godot(tmp_path, "--script", "res://customize.gd")
    scene_before = (output / "Hero.tscn").read_bytes()
    resource_before = (output / "Hero_frames.tres").read_bytes()
    image = Image.new("RGBA", (8, 8))
    image.putpixel((7, 7), (255, 50, 20, 128))
    image.save(frames[2])
    plan = exporter.prepare()
    assert plan.updates == ["attack: replace frame 3 image"]
    assert not plan.conflicts
    plan.apply()
    assert (output / "Hero.tscn").read_bytes() == scene_before
    assert (output / "Hero_frames.tres").read_bytes() == resource_before
    (tmp_path / "verify.gd").write_text(
        """extends SceneTree
func _initialize():
    call_deferred("verify")
func verify():
    var scene = load("res://assets/Hero.tscn").instantiate()
    root.add_child(scene)
    var frames = scene.sprite_frames
    assert(frames.get_animation_speed("attack") == 8.0)
    assert(not frames.get_animation_loop("attack"))
    assert(frames.get_frame_duration("attack", 3) == 3.5)
    assert(frames.get_frame_count("attack") == 6)
    assert(frames.get_meta("frame_event")["attack:3"] == "strike")
    assert(scene.get_meta("health") == 100)
    assert(scene.get_script().resource_path == "res://actor.gd")
    assert(scene.get_node("Hitbox/Shape").shape.size == Vector2(6, 9))
    assert(scene.get_node("Hitbox").collision_layer == 2)
    assert(scene.get_node("Hitbox").collision_mask == 4)
    var image = frames.get_frame_texture("attack", 2).get_image()
    assert(image.get_pixel(7, 7).is_equal_approx(Color8(255, 50, 20, 128)))
    scene.get_node("Events").play("attack-events")
    await create_timer(0.4).timeout
    assert(scene.get_meta("hits", 0) == 1)
    scene.play("attack")
    await scene.animation_finished
    assert(scene.frame == 5)
    print("PRESERVATION_VERIFIED")
    quit()
""",
        encoding="utf-8",
    )
    # A new process imports the revised PNG, loads the original scene, and runs
    # both the gameplay event and non-looping animation to completion.
    run_godot(tmp_path, "--editor", "--import")
    assert "PRESERVATION_VERIFIED" in run_godot(tmp_path, "--script", "res://verify.gd")
    assert exporter.prepare().unchanged
    # Also exercise a text property patch after Godot has resaved the resource.
    sprite.animations["attack"].frame_durations[4] = 2.0
    hold_plan = exporter.prepare()
    assert len(hold_plan.updates) == 1 and "frame 5 duration" in hold_plan.updates[0]
    hold_plan.apply()
    (tmp_path / "verify.gd").write_text(
        (tmp_path / "verify.gd")
        .read_text()
        .replace(
            'assert(frames.get_frame_count("attack") == 6)',
            'assert(frames.get_frame_count("attack") == 6)\n    assert(is_equal_approx(frames.get_frame_duration("attack", 4) / 8.0, 0.2))',
        )
    )
    assert "PRESERVATION_VERIFIED" in run_godot(tmp_path, "--script", "res://verify.gd")

    # Delete a frame, approve the preview, and verify surviving authored timing.
    sprite.animations["attack"].select_frames([0, 2, 3, 4, 5])
    sheet_before = (output / "Hero_sheet.png").read_bytes()
    delete_plan = GodotSpriteExporter(sprite, str(output)).prepare()
    assert any("6 → 5" in change for change in delete_plan.updates)
    assert delete_plan.notices
    delete_plan.apply()
    assert (output / "Hero.tscn").read_bytes() == scene_before
    assert (output / "Hero_sheet.png").read_bytes() == sheet_before
    script = (tmp_path / "verify.gd").read_text()
    script = script.replace('get_frame_count("attack") == 6', 'get_frame_count("attack") == 5')
    script = script.replace(
        'get_frame_duration("attack", 3) == 3.5', 'get_frame_duration("attack", 2) == 3.5'
    )
    script = script.replace(
        'get_frame_duration("attack", 4) / 8.0', 'get_frame_duration("attack", 3) / 8.0'
    )
    script = script.replace('get_frame_texture("attack", 2)', 'get_frame_texture("attack", 1)')
    script = script.replace("scene.frame == 5", "scene.frame == 4")
    (tmp_path / "verify.gd").write_text(script)
    assert "PRESERVATION_VERIFIED" in run_godot(tmp_path, "--script", "res://verify.gd")
    assert GodotSpriteExporter(sprite, str(output)).prepare().unchanged

    # Add a frame without relocating any existing atlas cell; import the grown sheet.
    added = tmp_path / "added-frame.png"
    image = Image.new("RGBA", (8, 8))
    image.putpixel((1, 7), (20, 40, 60, 128))
    image.save(added)
    sprite.animations["attack"].frames.insert(2, str(added))
    sprite.animations["attack"].frame_durations.insert(2, 2)
    add_plan = GodotSpriteExporter(sprite, str(output)).prepare()
    assert any("5 → 6" in change for change in add_plan.updates)
    add_plan.apply()
    assert (output / "Hero.tscn").read_bytes() == scene_before
    script = script.replace('get_frame_count("attack") == 5', 'get_frame_count("attack") == 6')
    script = script.replace(
        'get_frame_duration("attack", 2) == 3.5', 'get_frame_duration("attack", 3) == 3.5'
    )
    script = script.replace(
        'get_frame_duration("attack", 3) / 8.0', 'get_frame_duration("attack", 4) / 8.0'
    )
    script = script.replace("scene.frame == 4", "scene.frame == 5")
    script = script.replace(
        'assert(frames.get_frame_count("attack") == 6)',
        'assert(frames.get_frame_count("attack") == 6)\n    assert(is_equal_approx(frames.get_frame_duration("attack", 2) / 8.0, 0.2))\n    assert(frames.get_frame_texture("attack", 2).get_image().get_pixel(1, 7).is_equal_approx(Color8(20, 40, 60, 128)))',
    )
    (tmp_path / "verify.gd").write_text(script)
    run_godot(tmp_path, "--editor", "--import")
    assert "PRESERVATION_VERIFIED" in run_godot(tmp_path, "--script", "res://verify.gd")
    assert GodotSpriteExporter(sprite, str(output)).prepare().unchanged

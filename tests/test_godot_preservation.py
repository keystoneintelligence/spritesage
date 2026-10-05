"""Revision contract: only source changes authorize updates to Godot assets."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from spritesage import godot_text
from spritesage.exporter import GodotProjectExporter, GodotSpriteExporter
from spritesage.godot_export_transaction import (
    BACKUP,
    PENDING,
    recover_pending_export,
    restore_previous_export,
)
from spritesage import godot_export_transaction as transaction
from spritesage.godot_preservation import MANIFEST
from spritesage.sprite_file import Animation, SpriteFile


@pytest.fixture
def asset(tmp_path):
    frames = []
    for index in range(6):
        path = tmp_path / f"attack-{index}.png"
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        image.putpixel((index, 1), (index * 30, 80, 150, 128))
        image.save(path)
        frames.append(str(path))
    idle = tmp_path / "idle.png"
    Image.new("RGBA", (8, 8), (10, 20, 30, 0)).save(idle)
    sprite = SpriteFile(
        "hero-id",
        "Hero",
        "",
        8,
        8,
        "",
        {
            "attack": Animation("attack", frames, 10, False, [1, 1, 2, 1, 1, 1]),
            "idle": Animation("idle", [str(idle)], 4, True),
        },
        include_base_image_in_animations=False,
    )
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "export"))
    exporter.export()
    return sprite, exporter


def files(root):
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def change_setting(path, name, property_name, value, frame=None):
    resource = path.read_text(encoding="utf-8")
    animation = godot_text.animations(resource)[name]
    if frame is None:
        span = animation[property_name]
    else:
        entries = godot_text.items(resource, animation["frames"])
        span = godot_text.fields(resource, entries[frame])[property_name]
    path.write_text(godot_text.patch(resource, [(span, value)]), encoding="utf-8")


def playback(path, name):
    resource = path.read_text(encoding="utf-8")
    animation = godot_text.animations(resource)[name]
    frames = godot_text.items(resource, animation["frames"])
    return (
        godot_text.scalar(resource, animation["speed"], allow_zero=True),
        godot_text.scalar(resource, animation["loop"]),
        [
            godot_text.scalar(resource, godot_text.fields(resource, frame)["duration"])
            for frame in frames
        ],
    )


def replace_frame(sprite, index=2):
    path = Path(sprite.animations["attack"].frames[index])
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.putpixel((7, 7), (255, 50, 20, 128))
    image.save(path)
    return image


def test_first_export_stages_without_touching_destination(tmp_path):
    frame = tmp_path / "new.png"
    Image.new("RGBA", (8, 8)).save(frame)
    sprite = SpriteFile("new", "New", "", 8, 8, "", {"idle": Animation("idle", [str(frame)])})
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "new-export"))
    plan = exporter.prepare()
    assert not exporter.output_dir.exists()
    assert not plan.updates and not plan.conflicts
    assert plan.creations == ["New: create Godot asset"]
    plan.apply()
    assert (exporter.output_dir / "New.tscn").exists()
    assert (exporter.output_dir / MANIFEST).exists()


def test_unchanged_export_preserves_bytes_and_modification_times(asset):
    _, exporter = asset
    before = files(exporter.output_dir)
    assert exporter.prepare().unchanged
    exporter.export()
    assert files(exporter.output_dir) == before


def test_art_update_preserves_gameplay_timing_metadata_and_sibling_pixels(asset):
    sprite, exporter = asset
    root = exporter.output_dir
    scene = root / "Hero.tscn"
    scene.write_text(
        scene.read_text()
        + '\n[node name="Hitbox" type="Area2D" parent="."]\nmetadata/hit_event = "strike"\n',
        encoding="utf-8",
    )
    scene_before = scene.read_bytes()
    resource = root / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8.0")
    change_setting(resource, "attack", "duration", "3.5", frame=3)
    resource.write_text(
        resource.read_text() + '\nmetadata/gameplay = {"event": "hit", "data": [1, 2]}\n',
        encoding="utf-8",
    )
    resource_before = resource.read_bytes()
    sheet = root / "Hero_sheet.png"
    before = Image.open(sheet).convert("RGBA")
    replacement = replace_frame(sprite)
    plan = exporter.prepare()
    assert plan.updates == ["attack: replace frame 3 image"]
    assert not plan.conflicts
    plan.apply()
    assert scene.read_bytes() == scene_before
    assert resource.read_bytes() == resource_before
    assert playback(resource, "attack") == (8, False, [1, 1, 2, 3.5, 1, 1])
    manifest = json.loads((root / MANIFEST).read_bytes())
    x, y, w, h = manifest["slots"]["attack"][2]["region"]
    after = Image.open(sheet).convert("RGBA")
    assert after.crop((x, y, x + w, y + h)).tobytes() == replacement.tobytes()
    before.paste(replacement, (x, y))
    assert after.tobytes() == before.tobytes()
    assert exporter.prepare().unchanged


def test_one_hold_update_preserves_godot_fps_loop_and_other_holds(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8")
    change_setting(resource, "attack", "loop", "true")
    change_setting(resource, "attack", "duration", "4", frame=4)
    before_sheet = (exporter.output_dir / "Hero_sheet.png").read_bytes()
    sprite.animations["attack"].frame_durations[3] = 1.8
    plan = exporter.prepare()
    assert plan.updates == ["attack: frame 4 duration: 125 ms → 180 ms"]
    assert not plan.conflicts
    plan.apply()
    assert playback(resource, "attack") == (8, True, [1, 1, 2, 1.44, 4, 1])
    assert (exporter.output_dir / "Hero_sheet.png").read_bytes() == before_sheet


def test_conflicting_fps_requires_explicit_authorization_and_shows_actual_value(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8")
    sprite.animations["attack"].fps = 12.5
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert plan.conflicts == ["attack: fps: 8.0 → 12.5"]
    with pytest.raises(ValueError, match="explicit confirmation"):
        plan.apply()
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack")[0] == 12.5


def test_godot_only_changes_survive_noop(asset):
    _, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "7")
    before = files(exporter.output_dir)
    assert exporter.prepare().unchanged
    exporter.export()
    assert files(exporter.output_dir) == before


def test_same_change_in_both_apps_acknowledges_without_rewriting_resource(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "12.5")
    sprite.animations["attack"].fps = 12.5
    before = resource.read_bytes()
    plan = exporter.prepare()
    assert not plan.updates and not plan.conflicts
    plan.apply()
    assert resource.read_bytes() == before
    assert exporter.prepare().unchanged


@pytest.mark.parametrize("mutate", ["rename", "canvas", "identity", "filter"])
def test_structural_edits_are_planned_without_changing_destination(asset, mutate):
    sprite, exporter = asset
    if mutate == "rename":
        sprite.animations["renamed"] = sprite.animations.pop("attack")
    elif mutate == "canvas":
        sprite.width = 16
    elif mutate == "identity":
        sprite.uuid = "other"
    elif mutate == "filter":
        sprite.pixel_art = False
    before = files(exporter.output_dir)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert plan.writes
    assert files(exporter.output_dir) == before


def test_godot_texture_mapping_changes_are_reviewable(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    resource.write_text(
        resource.read_text().replace("Rect2(0, 0, 8, 8)", "Rect2(8, 0, 8, 8)"), encoding="utf-8"
    )
    replace_frame(sprite)
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert plan.updates and plan.file_diffs
    assert files(exporter.output_dir) == before


def test_resaved_godot_resources_keep_unknown_fields_and_extra_animations(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    value = resource.read_text().replace(
        '"frames": [', '"custom": {"quoted": "braces } [,", "nested": [1, 2]},\n    "frames": ['
    )
    marker = value.rfind("]\n")
    value = (
        value[:marker]
        + '{"frames": [], "loop": true, "name": &"engine-only", "speed": 6.0},\n'
        + value[marker:]
    )
    resource.write_text(value, encoding="utf-8")
    sprite.animations["attack"].fps = 11
    exporter.export()
    after = resource.read_text()
    assert '"name": &"engine-only"' in after
    assert '"quoted": "braces } [,", "nested": [1, 2]' in after
    assert playback(resource, "attack")[0] == 11


def test_res_paths_resolve_to_actual_destination(asset, tmp_path):
    sprite, exporter = asset
    (tmp_path / "project.godot").write_text("config_version=5\n")
    resource = exporter.output_dir / "Hero_frames.tres"
    resource.write_text(
        resource.read_text().replace('path="Hero_sheet.png"', 'path="res://export/Hero_sheet.png"')
    )
    sprite.animations["attack"].fps = 11
    exporter.export()
    resource.write_text(
        resource.read_text().replace(
            "res://export/Hero_sheet.png", "res://elsewhere/Hero_sheet.png"
        )
    )
    assert exporter.prepare().unchanged
    replace_frame(sprite)
    plan = exporter.prepare()
    assert plan.updates and plan.file_diffs


def test_export_without_manifest_adopts_without_touching_destination(asset):
    _, exporter = asset
    (exporter.output_dir / MANIFEST).unlink()
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert plan.notices
    assert (exporter.output_dir / MANIFEST) in plan.writes
    assert files(exporter.output_dir) == before


@pytest.mark.parametrize("changed", ["destination", "source"])
def test_changed_files_after_preview_abort(asset, changed):
    sprite, exporter = asset
    replace_frame(sprite)
    plan = exporter.prepare()
    if changed == "destination":
        path = exporter.output_dir / "Hero.tscn"
        path.write_text(path.read_text() + '\nmetadata/new = "keep"\n')
    else:
        path = Path(sprite.animations["attack"].frames[2])
        Image.new("RGBA", (8, 8)).save(path)
    before = files(exporter.output_dir)
    with pytest.raises(ValueError, match="after the export preview"):
        plan.apply()
    assert files(exporter.output_dir) == before


def test_transaction_failure_rolls_back_sheet_resource_and_manifest(asset, monkeypatch):
    sprite, exporter = asset
    replace_frame(sprite)
    sprite.animations["attack"].fps = 11
    before = {name: contents for name, (contents, _) in files(exporter.output_dir).items()}
    plan = exporter.prepare()
    original = transaction.atomic_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if Path(path).name == MANIFEST and not failed:
            failed = True
            raise OSError("simulated disk failure")
        original(path, data)

    monkeypatch.setattr(transaction, "atomic_write", fail_once)
    with pytest.raises(OSError, match="simulated"):
        plan.apply()
    assert {name: contents for name, (contents, _) in files(exporter.output_dir).items()} == before
    assert not (exporter.output_dir / PENDING).exists()
    exporter.export()
    assert playback(exporter.output_dir / "Hero_frames.tres", "attack")[0] == 11


def test_recovery_after_interruption_restores_previous_files(asset):
    _, exporter = asset
    root = exporter.output_dir
    resource = root / "Hero_frames.tres"
    original = resource.read_bytes()
    pending = {
        "version": 1,
        "before": {resource.name: base64.b64encode(original).decode(), "partial.txt": None},
    }
    pending["after"] = {
        resource.name: hashlib.sha256(b"incomplete").hexdigest(),
        "partial.txt": hashlib.sha256(b"partial").hexdigest(),
    }
    (root / PENDING).write_text(json.dumps(pending))
    resource.write_bytes(b"incomplete")
    (root / "partial.txt").write_text("partial")
    recover_pending_export(root)
    assert resource.read_bytes() == original
    assert not (root / "partial.txt").exists()
    assert not (root / PENDING).exists()
    assert exporter.prepare().unchanged


def test_restore_previous_export_restores_baseline_and_all_updated_assets(asset):
    sprite, exporter = asset
    before = {
        name: contents
        for name, (contents, _) in files(exporter.output_dir).items()
        if name != BACKUP
    }
    replace_frame(sprite)
    sprite.animations["attack"].fps = 11
    exporter.export()
    restore_previous_export(exporter.output_dir)
    assert {name: contents for name, (contents, _) in files(exporter.output_dir).items()} == before
    assert exporter.prepare().updates


def test_recovery_rejects_paths_outside_export_root(tmp_path):
    (tmp_path / PENDING).write_text(json.dumps({"version": 1, "before": {"../outside.txt": None}}))
    with pytest.raises(ValueError, match="Unsafe"):
        recover_pending_export(tmp_path)


def test_project_plans_all_sprites_before_any_write(asset, tmp_path):
    sprite, exporter = asset
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    other = SpriteFile(
        "other",
        "Other",
        "",
        8,
        8,
        "",
        {"idle": sprite.animations["idle"]},
        include_base_image_in_animations=False,
    )
    other.save(str(tmp_path / "other.sprite"), str(tmp_path))
    project = GodotProjectExporter(str(tmp_path), str(tmp_path / "project-export"))
    plan = project.prepare()
    assert len(plan.creations) == 2
    assert not project.output_dir.exists()
    plan.apply()
    sprite.animations["attack"].fps = 11
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    other.uuid = "changed-identity"
    other.save(str(tmp_path / "other.sprite"), str(tmp_path))
    before = files(project.output_dir)
    plan = project.prepare()
    assert any("fps" in value for value in plan.updates)
    assert files(project.output_dir) == before


def test_new_opaque_export_runs_legacy_background_removal_and_resize(tmp_path, monkeypatch):
    from spritesage import spritesheet

    calls = []

    def cleanup(images):
        calls.extend(image.copy() for image in images)
        return [Image.new("RGBA", image.size, (20, 40, 60, 128)) for image in images]

    monkeypatch.setattr(spritesheet, "remove_background_images", cleanup)
    path = tmp_path / "opaque.png"
    Image.new("RGB", (16, 16), "white").save(path)
    original = path.read_bytes()
    sprite = SpriteFile(
        "opaque",
        "Opaque",
        "",
        8,
        8,
        "",
        {"idle": Animation("idle", [str(path)])},
        include_base_image_in_animations=False,
    )
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "opaque-export"))
    exporter.export()
    assert len(calls) == 1 and calls[0].size == (8, 8)
    assert Image.open(exporter.output_dir / "Opaque_sheet.png").getpixel((0, 0)) == (
        20,
        40,
        60,
        128,
    )
    assert path.read_bytes() == original
    assert exporter.prepare().unchanged
    assert len(calls) == 1


def test_new_export_keeps_meaningful_alpha_without_running_cleanup(tmp_path, monkeypatch):
    from spritesage import spritesheet

    def unexpected_cleanup(*args):
        raise AssertionError("Meaningful source alpha must bypass background removal")

    monkeypatch.setattr(spritesheet, "remove_background_images", unexpected_cleanup)
    path = tmp_path / "alpha.png"
    image = Image.new("RGBA", (8, 8), (20, 40, 60, 255))
    image.putpixel((0, 0), (30, 50, 70, 0))
    image.putpixel((1, 1), (50, 70, 90, 128))
    image.save(path)
    sprite = SpriteFile(
        "alpha",
        "Alpha",
        "",
        8,
        8,
        "",
        {"idle": Animation("idle", [str(path)])},
        include_base_image_in_animations=False,
    )
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "alpha-export"))
    exporter.export()
    exported = Image.open(exporter.output_dir / "Alpha_sheet.png").convert("RGBA")
    expected = Image.new("RGBA", (8, 8))
    expected.alpha_composite(image)
    assert exported.tobytes() == expected.tobytes()
    assert exported.getpixel((1, 1))[3] == 128


def test_opaque_replacement_cleans_and_resizes_only_changed_frame(asset, monkeypatch):
    from spritesage import spritesheet

    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    scene = exporter.output_dir / "Hero.tscn"
    change_setting(resource, "attack", "speed", "8")
    before_resource, before_scene = resource.read_bytes(), scene.read_bytes()
    before_sheet = Image.open(exporter.output_dir / "Hero_sheet.png").convert("RGBA")
    image = Image.new("RGB", (16, 16), "white")
    image.save(sprite.animations["attack"].frames[2])
    source_bytes = Path(sprite.animations["attack"].frames[2]).read_bytes()
    calls = []

    def cleanup(images):
        calls.extend(image.copy() for image in images)
        return [Image.new("RGBA", image.size, (50, 80, 100, 128)) for image in images]

    monkeypatch.setattr(spritesheet, "remove_background_images", cleanup)
    plan = exporter.prepare()
    assert len(calls) == 1 and calls[0].size == (8, 8)
    assert plan.updates == ["attack: replace frame 3 image"]
    plan.apply()
    sheet = Image.open(exporter.output_dir / "Hero_sheet.png").convert("RGBA")
    manifest = json.loads((exporter.output_dir / MANIFEST).read_bytes())
    x, y, w, h = manifest["slots"]["attack"][2]["region"]
    expected = before_sheet.copy()
    expected.paste(Image.new("RGBA", (w, h), (50, 80, 100, 128)), (x, y))
    assert sheet.tobytes() == expected.tobytes()
    assert resource.read_bytes() == before_resource and scene.read_bytes() == before_scene
    assert Path(sprite.animations["attack"].frames[2]).read_bytes() == source_bytes
    assert exporter.prepare().unchanged
    assert len(calls) == 1


def test_static_sprite_update_keeps_scene_and_uses_stable_texture_path(tmp_path, monkeypatch):
    from spritesage import exporter as module

    calls = []

    def cleanup(image):
        calls.append(image.copy())
        result = image.convert("RGBA")
        result.putpixel((7, 7), (0, 0, 0, 0))
        return result

    monkeypatch.setattr(module, "remove_background_image", cleanup)
    path = tmp_path / "base.png"
    image = Image.new("RGBA", (8, 8), (20, 40, 60, 255))
    image.save(path)
    sprite = SpriteFile("static", "Static", "", 8, 8, str(path), {})
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "static-export"))
    exporter.export()
    scene = exporter.output_dir / "Static.tscn"
    scene.write_text(
        scene.read_text(encoding="utf-8") + '\nmetadata/gameplay = "keep"\n', encoding="utf-8"
    )
    before_scene = scene.read_bytes()
    before_files = files(exporter.output_dir)
    assert exporter.prepare().unchanged
    assert files(exporter.output_dir) == before_files
    replacement = tmp_path / "renamed-source.png"
    image.putpixel((0, 0), (90, 30, 50, 128))
    image.save(replacement)
    sprite.base_image = str(replacement)
    plan = exporter.prepare()
    assert plan.updates == ["Static: replace sprite image"]
    plan.apply()
    assert scene.read_bytes() == before_scene
    assert Image.open(exporter.output_dir / "base.png").getpixel((0, 0)) == (90, 30, 50, 128)
    assert not (exporter.output_dir / replacement.name).exists()
    assert len(calls) == 2
    assert (exporter.output_dir / "base.png").is_file()
    assert not (exporter.output_dir / "Static.png").exists()
    assert Image.open(exporter.output_dir / "base.png").getpixel((7, 7))[3] == 0
    Image.new("RGBA", (16, 16)).save(replacement)
    exporter.export()
    assert Image.open(exporter.output_dir / "base.png").size == (16, 16)
    assert scene.read_bytes() == before_scene


def test_godot_image_edits_conflict_only_for_the_replaced_cell(asset):
    sprite, exporter = asset
    sheet_path = exporter.output_dir / "Hero_sheet.png"
    image = Image.open(sheet_path).convert("RGBA")
    image.putpixel((1, 1), (30, 40, 50, 255))  # Godot edit to a sibling cell.
    image.save(sheet_path)
    replace_frame(sprite)
    plan = exporter.prepare()
    assert not plan.conflicts
    plan.apply()
    assert Image.open(sheet_path).getpixel((1, 1)) == (30, 40, 50, 255)
    # Editing the selected cell on both sides requires explicit approval.
    manifest = json.loads((exporter.output_dir / MANIFEST).read_bytes())
    x, y, _, _ = manifest["slots"]["attack"][2]["region"]
    image = Image.open(sheet_path).convert("RGBA")
    image.putpixel((x, y), (50, 60, 70, 255))
    image.save(sheet_path)
    replacement = Image.open(sprite.animations["attack"].frames[2]).convert("RGBA")
    replacement.putpixel((0, 0), (70, 80, 90, 255))
    replacement.save(sprite.animations["attack"].frames[2])
    assert exporter.prepare().conflicts == ["attack: replace frame 3 image"]


def test_paused_godot_animation_is_preserved_for_art_only_update(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "0.0")
    replace_frame(sprite)
    plan = exporter.prepare()
    assert not plan.conflicts
    plan.apply()
    assert '"speed": 0.0' in resource.read_text(encoding="utf-8")


def test_duration_conflict_compares_actual_godot_milliseconds(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8.0")
    change_setting(resource, "attack", "duration", "3.5", frame=3)
    sprite.animations["attack"].frame_durations[3] = 1.8
    plan = exporter.prepare()
    assert plan.conflicts == ["attack: frame 4 duration: 437.5 ms → 180 ms"]
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack") == (8, False, [1, 1, 2, 1.44, 1, 1])


def test_recovery_refuses_to_overwrite_later_godot_edits(asset):
    sprite, exporter = asset
    replace_frame(sprite)
    exporter.export()
    resource = exporter.output_dir / "Hero_sheet.png"
    image = Image.open(resource).convert("RGBA")
    image.putpixel((0, 0), (30, 60, 90, 255))
    image.save(resource)
    before = files(exporter.output_dir)
    with pytest.raises(ValueError, match="Recovery needs review"):
        restore_previous_export(exporter.output_dir)
    assert files(exporter.output_dir) == before


def test_project_commit_failure_rolls_back_every_sprite(asset, tmp_path, monkeypatch):
    sprite, _ = asset
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    other = SpriteFile(
        "other",
        "Other",
        "",
        8,
        8,
        "",
        {"idle": sprite.animations["idle"]},
        include_base_image_in_animations=False,
    )
    other.save(str(tmp_path / "other.sprite"), str(tmp_path))
    exporter = GodotProjectExporter(str(tmp_path), str(tmp_path / "project-output"))
    plan = exporter.prepare()
    write = transaction.atomic_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if Path(path).parent.name == "other" and Path(path).name == MANIFEST and not failed:
            failed = True
            raise OSError("second sprite failure")
        write(path, data)

    monkeypatch.setattr(transaction, "atomic_write", fail_once)
    with pytest.raises(OSError, match="second sprite"):
        plan.apply()
    assert files(exporter.output_dir) == {}


def test_godot_float_rounding_is_not_an_authored_conflict(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "10.0000001")
    change_setting(resource, "attack", "duration", "2.00000002", frame=2)
    sprite.animations["attack"].fps = 12.5
    sprite.animations["attack"].frame_durations[2] = 2.5
    plan = exporter.prepare()
    assert len(plan.updates) == 2
    assert not plan.conflicts
    plan.apply()
    assert playback(resource, "attack")[0] == 12.5


def test_shared_source_cannot_change_between_project_plans(tmp_path):
    from spritesage.godot_export_transaction import ExportPlan

    path = tmp_path / "shared.png"
    first = ExportPlan(root=tmp_path, guards={path: b"first"})
    second = ExportPlan(root=tmp_path, guards={path: b"second"})
    with pytest.raises(ValueError, match="Shared files changed"):
        first.merge(second)


def test_changed_scene_resource_binding_cannot_report_orphan_update(asset):
    sprite, exporter = asset
    scene = exporter.output_dir / "Hero.tscn"
    scene.write_text(
        scene.read_text().replace('path="Hero_frames.tres"', 'path="other_frames.tres"')
    )
    before = files(exporter.output_dir)
    replace_frame(sprite)
    plan = exporter.prepare()
    assert any("binding" in value for value in plan.updates)
    assert scene in plan.writes
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert 'path="Hero_frames.tres"' in scene.read_text()


def test_resume_paused_animation_can_also_set_frame_duration(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "0.0")
    sprite.animations["attack"].fps = 12
    sprite.animations["attack"].frame_durations[2] = 3
    plan = exporter.prepare()
    assert any("paused (0 FPS)" in update for update in plan.updates)
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack") == (12, False, [1, 1, 3, 1, 1, 1])


def test_static_preview_manifest_keeps_its_existing_filename(tmp_path, monkeypatch):
    from spritesage import exporter as module

    monkeypatch.setattr(module, "remove_background_image", lambda image: image.convert("RGBA"))
    path = tmp_path / "base.png"
    Image.new("RGBA", (8, 8), (30, 40, 50, 255)).save(path)
    sprite = SpriteFile("static", "Static", "", 8, 8, str(path), {})
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "export"))
    exporter.export()
    (exporter.output_dir / "base.png").rename(exporter.output_dir / "Static.png")
    manifest_path = exporter.output_dir / MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    del manifest["base_file"]
    manifest_path.write_text(json.dumps(manifest))
    scene = exporter.output_dir / "Static.tscn"
    scene.write_text(scene.read_text().replace('path="base.png"', 'path="Static.png"'))
    before_scene = scene.read_bytes()
    Image.new("RGBA", (8, 8), (90, 80, 70, 255)).save(path)
    exporter.export()
    assert Image.open(exporter.output_dir / "Static.png").getpixel((0, 0)) == (90, 80, 70, 255)
    assert scene.read_bytes() == before_scene
    assert not (exporter.output_dir / "base.png").exists()


def test_background_removal_failure_does_not_touch_existing_export(asset, monkeypatch):
    from spritesage import spritesheet

    sprite, exporter = asset
    before = files(exporter.output_dir)
    Image.new("RGB", (8, 8), "white").save(sprite.animations["attack"].frames[2])

    def fail(images):
        raise RuntimeError("background removal failed")

    monkeypatch.setattr(spritesheet, "remove_background_images", fail)
    with pytest.raises(RuntimeError, match="background removal failed"):
        exporter.prepare()
    assert files(exporter.output_dir) == before


def test_static_same_art_already_in_godot_only_acknowledges_manifest(tmp_path, monkeypatch):
    from spritesage import exporter as module

    monkeypatch.setattr(module, "remove_background_image", lambda image: image.convert("RGBA"))
    path = tmp_path / "base.png"
    Image.new("RGBA", (8, 8), (30, 40, 50, 255)).save(path)
    sprite = SpriteFile("static", "Static", "", 8, 8, str(path), {})
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "export"))
    exporter.export()
    image = Image.new("RGBA", (8, 8), (90, 80, 70, 255))
    image.save(path)
    destination = exporter.output_dir / "base.png"
    image.save(destination)
    before = (destination.read_bytes(), destination.stat().st_mtime_ns)
    plan = exporter.prepare()
    assert not plan.updates and not plan.conflicts
    assert list(plan.writes) == [exporter.output_dir / MANIFEST]
    plan.apply()
    assert (destination.read_bytes(), destination.stat().st_mtime_ns) == before


def test_frame_deletion_is_reviewable_and_keeps_surviving_godot_data(asset, monkeypatch):
    from spritesage import spritesheet

    sprite, exporter = asset
    root = exporter.output_dir
    resource = root / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8")
    change_setting(resource, "attack", "loop", "true")
    change_setting(resource, "attack", "duration", "3.5", frame=3)
    value = resource.read_text()
    record = godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[3]
    value = value[: record.start + 1] + '"game_event": "strike", ' + value[record.start + 1 :]
    resource.write_text(value + '\nmetadata/gameplay = {"hit_frame": 3}\n')
    scene_before = (root / "Hero.tscn").read_bytes()
    sheet_before = (root / "Hero_sheet.png").read_bytes()
    manifest_before = json.loads((root / MANIFEST).read_bytes())
    before = files(root)
    sprite.animations["attack"].frames.pop(2)
    sprite.animations["attack"].frame_durations.pop(2)
    monkeypatch.setattr(
        spritesheet,
        "remove_background_images",
        lambda images: pytest.fail("Deletion must not process surviving artwork"),
    )
    plan = exporter.prepare()
    assert any("frame count: 6 → 5" in change for change in plan.updates)
    assert "attack: remove frames: 3" in plan.updates
    assert plan.notices and "frame-index" in plan.notices[0]
    assert not plan.conflicts
    assert files(root) == before  # Preparing and abandoning the plan writes nothing.
    plan.apply()
    assert playback(resource, "attack") == (8, True, [1, 1, 3.5, 1, 1])
    assert '"game_event": "strike"' in resource.read_text()
    assert 'metadata/gameplay = {"hit_frame": 3}' in resource.read_text()
    assert (root / "Hero.tscn").read_bytes() == scene_before
    assert (root / "Hero_sheet.png").read_bytes() == sheet_before
    manifest = json.loads((root / MANIFEST).read_bytes())
    expected = manifest_before["slots"]["attack"][:2] + manifest_before["slots"]["attack"][3:]
    assert manifest["slots"]["attack"] == expected
    assert exporter.prepare().unchanged
    replace_frame(sprite, 2)
    exporter.export()
    assert playback(resource, "attack") == (8, True, [1, 1, 3.5, 1, 1])


def test_deleting_authored_frame_discloses_its_godot_edits_and_requires_approval(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "duration", "3.5", frame=2)
    sprite.animations["attack"].frames.pop(2)
    sprite.animations["attack"].frame_durations.pop(2)
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert plan.conflicts == ["attack: remove frame 3, including its Godot edits"]
    with pytest.raises(ValueError, match="explicit confirmation"):
        plan.apply()
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack")[2] == [1, 1, 1, 1, 1]


def test_frame_reorder_keeps_holds_and_atlas_identity_with_surviving_frames(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "duration", "3.5", frame=3)
    sheet_before = (exporter.output_dir / "Hero_sheet.png").read_bytes()
    old_slots = json.loads((exporter.output_dir / MANIFEST).read_bytes())["slots"]["attack"]
    sprite.animations["attack"].select_frames([5, 4, 3, 2, 1, 0])
    plan = exporter.prepare()
    assert plan.updates and plan.notices
    plan.apply()
    assert playback(resource, "attack")[2] == [1, 1, 3.5, 2, 1, 1]
    assert (exporter.output_dir / "Hero_sheet.png").read_bytes() == sheet_before
    assert json.loads((exporter.output_dir / MANIFEST).read_bytes())["slots"]["attack"] == list(
        reversed(old_slots)
    )
    assert exporter.prepare().unchanged


def test_added_frame_expands_sheet_without_moving_or_reprocessing_existing_cells(
    asset, tmp_path, monkeypatch
):
    from spritesage import spritesheet

    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8")
    before_sheet = Image.open(exporter.output_dir / "Hero_sheet.png").convert("RGBA")
    path = tmp_path / "added.png"
    Image.new("RGB", (16, 16), "white").save(path)
    calls = []

    def cleanup(images):
        calls.extend(images)
        return [Image.new("RGBA", image.size, (20, 40, 60, 128)) for image in images]

    monkeypatch.setattr(spritesheet, "remove_background_images", cleanup)
    sprite.animations["attack"].frames.insert(2, str(path))
    sprite.animations["attack"].frame_durations.insert(2, 2)
    plan = exporter.prepare()
    assert len(calls) == 1 and calls[0].size == (8, 8)
    assert "attack: add frame 3 image" in plan.updates
    plan.apply()
    sheet = Image.open(exporter.output_dir / "Hero_sheet.png").convert("RGBA")
    assert (
        sheet.crop((0, 0, before_sheet.width, before_sheet.height)).tobytes()
        == before_sheet.tobytes()
    )
    assert playback(resource, "attack")[2] == [1, 1, 1.6, 2, 1, 1, 1]
    assert exporter.prepare().unchanged


def test_deleting_last_frame_keeps_empty_animation_and_user_scene(asset):
    sprite, exporter = asset
    resource = exporter.output_dir / "Hero_frames.tres"
    before_scene = (exporter.output_dir / "Hero.tscn").read_bytes()
    sprite.animations["idle"].select_frames([])
    exporter.export()
    assert playback(resource, "idle") == (4, True, [])
    assert (exporter.output_dir / "Hero.tscn").read_bytes() == before_scene
    sprite.animations["attack"].select_frames([])
    exporter = GodotSpriteExporter(sprite, str(exporter.output_dir))
    plan = exporter.prepare()
    assert any("6 → 0" in change for change in plan.updates)
    plan.apply()
    assert playback(resource, "attack") == (10, False, [])
    assert exporter.prepare().unchanged


def test_duplicate_frame_is_reviewable_and_preserves_existing_sheet(asset):
    sprite, exporter = asset
    before = (exporter.output_dir / "Hero_sheet.png").read_bytes()
    sprite.animations["attack"].select_frames([0, 1, 2, 2, 3, 4, 5])
    plan = exporter.prepare()
    assert any("6 → 7" in change for change in plan.updates)
    plan.apply()
    assert playback(exporter.output_dir / "Hero_frames.tres", "attack")[2] == [1, 1, 2, 2, 1, 1, 1]
    assert (exporter.output_dir / "Hero_sheet.png").read_bytes() == before
    assert exporter.prepare().unchanged


def test_repeated_frame_can_have_an_independent_duration_on_insertion(asset):
    sprite, exporter = asset
    animation = sprite.animations["attack"]
    animation.select_frames([0, 1, 2, 2, 3, 4, 5])
    animation.frame_durations[2] = 3
    exporter.export()
    assert playback(exporter.output_dir / "Hero_frames.tres", "attack")[2] == [1, 1, 3, 2, 1, 1, 1]
    assert exporter.prepare().unchanged


def test_project_frame_deletion_is_planned_without_writing_until_accepted(asset, tmp_path):
    sprite, _ = asset
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    project = GodotProjectExporter(str(tmp_path), str(tmp_path / "project-export"))
    project.export()
    before = files(project.output_dir)
    sprite.animations["attack"].select_frames([0, 1, 3, 4, 5])
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    plan = project.prepare()
    assert any("hero.sprite" in change and "6 → 5" in change for change in plan.updates)
    assert plan.notices and "hero.sprite" in plan.notices[0]
    assert files(project.output_dir) == before
    plan.apply()
    assert playback(project.output_dir / "hero" / "Hero_frames.tres", "attack")[2] == [
        1,
        1,
        1,
        1,
        1,
    ]

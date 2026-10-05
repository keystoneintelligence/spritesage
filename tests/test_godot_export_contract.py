"""User contract: review actual candidate files, then accept or leave every byte alone."""

import json

import pytest

from spritesage import godot_text
from spritesage.exporter import GodotSpriteExporter
from spritesage.godot_preservation import MANIFEST
from spritesage.godot_export_transaction import BACKUP
from spritesage.sprite_file import Animation
from tests.test_godot_preservation import (
    asset as asset,
    change_setting,
    files,
    playback,
    replace_frame,
)


def author_game_data(exporter):
    root = exporter.output_dir
    scene = root / "Hero.tscn"
    scene.write_text(
        scene.read_text()
        + '\n[node name="Hitbox" type="Area2D" parent="."]\n'
        + 'collision_layer = 8\ncollision_mask = 16\nmetadata/hit = {"event": "strike"}\n'
    )
    resource = root / "Hero_frames.tres"
    change_setting(resource, "attack", "speed", "8")
    change_setting(resource, "attack", "loop", "true")
    change_setting(resource, "attack", "duration", "3.5", frame=3)
    value = resource.read_text()
    end = value.rfind("]")
    value = (
        value[:end]
        + '{"frames": [], "loop": false, "name": &"game-only", "speed": 3},\n'
        + value[end:]
    )
    resource.write_text(
        value + '\nmetadata/game = {"attack:3": "strike", "nested": [1, {"x": 2}]}\n'
    )
    (root / "actor.gd").write_text("extends AnimatedSprite2D\n# authored gameplay\n")
    return scene, resource


@pytest.mark.parametrize(
    "edit",
    ["add", "delete", "rename", "canvas", "filter", "identity", "sprite-name", "paused", "legacy"],
)
def test_all_normal_edits_are_reviewable_without_touching_files(asset, edit):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    before_scene = scene.read_bytes()
    old_attack = playback(resource, "attack")
    if edit == "add":
        sprite.animations["new"] = Animation("new", sprite.animations["idle"].frames, 6, False)
    elif edit == "delete":
        del sprite.animations["idle"]
    elif edit == "rename":
        sprite.animations["strike"] = sprite.animations.pop("attack")
    elif edit == "canvas":
        sprite.width = 16
    elif edit == "filter":
        sprite.pixel_art = False
    elif edit == "identity":
        sprite.uuid = "replacement-id"
        replace_frame(sprite)
    elif edit == "sprite-name":
        sprite.name = "Renamed"
    elif edit == "paused":
        change_setting(resource, "attack", "speed", "0")
        sprite.animations["attack"].frame_durations[3] = 1.8
    elif edit == "legacy":
        (exporter.output_dir / MANIFEST).unlink()
        replace_frame(sprite)
    before = files(exporter.output_dir)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert files(exporter.output_dir) == before  # Prepare and Cancel preserve bytes AND mtimes.
    assert plan.updates, edit
    assert plan.file_diffs, edit
    assert all(
        plan.file_summaries.values()
    ), edit  # Diff the proposed artifacts, not just source intentions.
    expected_writes = dict(plan.writes)
    plan.apply(allow_conflicts=True)
    for path, content in expected_writes.items():
        assert path.read_bytes() == content  # Acceptance writes exactly the reviewed candidate.
    for name, previous in before.items():
        if exporter.output_dir / name not in expected_writes and name != BACKUP:
            assert files(exporter.output_dir)[name] == previous
    assert 'metadata/game = {"attack:3": "strike", "nested": [1, {"x": 2}]}' in resource.read_text()
    assert "game-only" in godot_text.animations(resource.read_text())
    assert (exporter.output_dir / "actor.gd").read_bytes() == before["actor.gd"][0]
    assert (
        'collision_layer = 8\ncollision_mask = 16\nmetadata/hit = {"event": "strike"}'
        in scene.read_text()
    )
    if edit not in ("filter", "sprite-name", "rename"):
        assert scene.read_bytes() == before_scene
    name = "strike" if edit == "rename" else "attack"
    if edit != "paused":
        assert playback(resource, name) == old_attack
    else:
        assert (
            playback(resource, name)[0] == 0
        )  # Store timing intent without resuming a paused animation.
        assert any("paused" in item.lower() for item in plan.notices)
    fresh = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert fresh.unchanged


@pytest.mark.parametrize(
    "godot_edit", ["count", "reorder", "atlas", "texture", "binding", "removed-animation"]
)
def test_godot_shape_edits_do_not_block_source_updates(asset, godot_edit):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    value = resource.read_text()
    animation = godot_text.animations(value)["attack"]
    records = godot_text.items(value, animation["frames"])
    if godot_edit == "count":
        value = godot_text.patch(
            value,
            [(animation["frames"], "[" + ",".join(s.text(value) for s in records[:-1]) + "]")],
        )
    elif godot_edit == "reorder":
        value = godot_text.patch(
            value,
            [(animation["frames"], "[" + ",".join(s.text(value) for s in reversed(records)) + "]")],
        )
    elif godot_edit == "atlas":
        value = value.replace("Rect2(0, 0, 8, 8)", "Rect2(8, 0, 8, 8)")
    elif godot_edit == "texture":
        frame = godot_text.fields(value, records[2])
        value = godot_text.patch(value, [(frame["texture"], "null")])
    elif godot_edit == "binding":
        scene.write_text(
            scene.read_text().replace('path="Hero_frames.tres"', 'path="other_frames.tres"')
        )
    elif godot_edit == "removed-animation":
        start = value.index("animations = [") + len("animations = ")
        span = godot_text.container(value, start)
        remaining = [
            s.text(value)
            for s in godot_text.items(value, span)
            if '"name": &"attack"' not in s.text(value)
        ]
        value = godot_text.patch(value, [(span, "[" + ",".join(remaining) + "]")])
    resource.write_text(value)
    # Godot-only changes alone must stay completely untouched.
    before = files(exporter.output_dir)
    assert exporter.prepare().unchanged
    assert files(exporter.output_dir) == before
    replace_frame(sprite)
    plan = exporter.prepare()
    assert plan.updates and plan.file_diffs
    assert files(exporter.output_dir) == before
    reviewed = dict(plan.writes)
    plan.apply(allow_conflicts=True)
    assert all(path.read_bytes() == data for path, data in reviewed.items())
    assert 'metadata/game = {"attack:3": "strike", "nested": [1, {"x": 2}]}' in resource.read_text()
    if godot_edit != "binding":
        assert scene.read_bytes() == before["Hero.tscn"][0]


def test_candidate_diff_lists_only_actual_changed_file(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    before = files(exporter.output_dir)
    sprite.animations["attack"].fps = 12
    plan = exporter.prepare()
    assert set(plan.file_diffs) == {resource}
    assert '"speed": 8' in plan.file_diffs[resource]
    assert '"speed": 12' in plan.file_diffs[resource]
    assert scene not in plan.writes
    assert files(exporter.output_dir) == before


def test_authored_unknown_variants_survive_structural_update(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    opaque = 'metadata/variants = {&"event": NodePath("Hitbox"), "packed": PackedFloat32Array(1, 2), "nested": [Transform2D(1, 0, 0, 1, 3, 4)]}\n'
    resource.write_text(resource.read_text() + opaque)
    sprite.animations["new"] = Animation("new", sprite.animations["idle"].frames, 6, False)
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    assert opaque in resource.read_text()
    manifest = json.loads((exporter.output_dir / MANIFEST).read_bytes())
    assert "new" in manifest["source"]["animations"]


def test_shared_godot_texture_does_not_overwrite_an_unedited_sibling(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    records = godot_text.items(value, godot_text.animations(value)["attack"]["frames"])
    first = godot_text.fields(value, records[0])
    selected = godot_text.fields(value, records[2])
    shared = selected["texture"].text(value)
    resource.write_text(godot_text.patch(value, [(first["texture"], shared)]))
    old_sheet = (exporter.output_dir / "Hero_sheet.png").read_bytes()
    replace_frame(sprite)
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    value = resource.read_text()
    records = godot_text.items(value, godot_text.animations(value)["attack"]["frames"])
    assert godot_text.fields(value, records[0])["texture"].text(value) == shared
    assert godot_text.fields(value, records[2])["texture"].text(value) != shared
    from PIL import Image
    import io

    before = Image.open(io.BytesIO(old_sheet)).convert("RGBA")
    after = Image.open(exporter.output_dir / "Hero_sheet.png").convert("RGBA")
    assert before.tobytes() == after.crop((0, 0, before.width, before.height)).tobytes()


def test_source_rename_then_art_update_keeps_stable_paths_and_timing(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    sprite.name = "Renamed"
    GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare().apply(allow_conflicts=True)
    before_scene = scene.read_bytes()
    before_resource = resource.read_bytes()
    before_playback = playback(resource, "attack")
    replace_frame(sprite)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    plan.apply(allow_conflicts=True)
    assert scene.read_bytes() == before_scene
    assert resource.read_bytes() == before_resource
    assert playback(resource, "attack") == before_playback
    assert not (exporter.output_dir / "Renamed.tscn").exists()


def test_canvas_update_then_art_update_keeps_new_regions_and_authored_frames(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    sprite.width = 16
    exporter = GodotSpriteExporter(sprite, str(exporter.output_dir))
    exporter.prepare().apply(allow_conflicts=True)
    before_scene, before_resource = scene.read_bytes(), resource.read_bytes()
    before_playback = playback(resource, "attack")
    replace_frame(sprite)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    plan.apply(allow_conflicts=True)
    assert scene.read_bytes() == before_scene
    assert resource.read_bytes() == before_resource
    assert playback(resource, "attack") == before_playback


def test_active_godot_resource_binding_is_preserved_when_target_exists(asset):
    sprite, exporter = asset
    scene, original = author_game_data(exporter)
    active = exporter.output_dir / "authored_frames.tres"
    active.write_bytes(original.read_bytes())
    change_setting(active, "attack", "speed", "6")
    scene.write_text(
        scene.read_text().replace('path="Hero_frames.tres"', 'path="authored_frames.tres"')
    )
    before_scene, before_original = scene.read_bytes(), original.read_bytes()
    replace_frame(sprite)
    plan = exporter.prepare()
    assert files(exporter.output_dir)["Hero.tscn"][0] == before_scene
    plan.apply(allow_conflicts=True)
    assert scene.read_bytes() == before_scene
    assert original.read_bytes() == before_original
    assert playback(active, "attack")[0] == 6
    assert GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare().unchanged


@pytest.mark.parametrize("record", ["unsupported", "invalid"])
def test_old_or_invalid_export_record_offers_adoption_instead_of_refusal(asset, record):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    manifest = exporter.output_dir / MANIFEST
    manifest.write_text('{"version": 2}' if record == "unsupported" else "broken json")
    before = files(exporter.output_dir)
    replace_frame(sprite)
    plan = exporter.prepare()
    assert plan.updates and plan.notices and plan.file_diffs
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack") == (8, True, [1, 1, 2, 3.5, 1, 1])


def test_delete_all_source_animations_keeps_an_empty_authored_sprite_scene(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    before_scene = scene.read_bytes()
    sprite.animations.clear()
    before = files(exporter.output_dir)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert plan.updates and plan.file_diffs
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert scene.read_bytes() == before_scene.replace(
        b'animation = &"attack"', b'animation = &"game-only"'
    )
    assert set(godot_text.animations(resource.read_text())) == {"game-only"}


def test_rename_updates_only_the_scene_animation_reference_that_would_break(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    before = scene.read_bytes()
    sprite.animations["strike"] = sprite.animations.pop("attack")
    plan = exporter.prepare()
    assert scene in plan.file_diffs
    plan.apply(allow_conflicts=True)
    expected = before.replace(b'animation = &"attack"', b'animation = &"strike"')
    assert scene.read_bytes() == expected
    assert playback(resource, "strike") == (8, True, [1, 1, 2, 3.5, 1, 1])


def test_inline_spriteframes_keep_their_binding_and_game_data(asset):
    sprite, exporter = asset
    scene, resource = author_game_data(exporter)
    value = resource.read_text()
    value = value[value.index("[ext_resource") :]
    value = value.replace("[resource]", '[sub_resource type="SpriteFrames" id="Frames_authored"]')
    old_scene = scene.read_text()
    node_start = old_scene.index("[node")
    header = old_scene[: old_scene.index("[ext_resource")]
    body = old_scene[node_start:]
    import re

    body = re.sub(
        r'sprite_frames = ExtResource\("[^"]+"\)',
        'sprite_frames = SubResource("Frames_authored")',
        body,
    )
    scene.write_text(header + value + "\n" + body)
    before_resource = resource.read_bytes()
    before = files(exporter.output_dir)
    replace_frame(sprite)
    plan = exporter.prepare()
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert 'sprite_frames = SubResource("Frames_authored")' in scene.read_text()
    assert resource.read_bytes() == before_resource
    assert 'metadata/game = {"attack:3": "strike", "nested": [1, {"x": 2}]}' in scene.read_text()
    assert "collision_layer = 8" in scene.read_text()
    assert GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare().unchanged


@pytest.mark.parametrize("edit", ["canvas", "animation", "legacy", "paused"])
def test_native_review_cancel_leaves_every_destination_file_untouched(asset, edit, qapp, tmp_path):
    from PySide6 import QtWidgets
    from PySide6.QtCore import QTimer
    from tests.test_export_ui import DummyExportWidget

    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    if edit == "canvas":
        sprite.width = 16
    elif edit == "animation":
        sprite.animations["new"] = Animation("new", sprite.animations["idle"].frames, 6, False)
    elif edit == "legacy":
        (exporter.output_dir / MANIFEST).unlink()
        replace_frame(sprite)
    else:
        change_setting(resource, "attack", "speed", "0")
        sprite.animations["attack"].frame_durations[2] = 3
    exporter = GodotSpriteExporter(sprite, str(exporter.output_dir))
    before = files(exporter.output_dir)
    widget = DummyExportWidget(str(tmp_path))
    reviewed = []

    def cancel():
        box = QtWidgets.QApplication.activeModalWidget()
        if isinstance(box, QtWidgets.QMessageBox):
            reviewed.append(box.informativeText())
            assert box.detailedText()
            assert box.button(QtWidgets.QMessageBox.StandardButton.Ok).text() == "Export"
            box.button(QtWidgets.QMessageBox.StandardButton.Cancel).click()

    timer = QTimer()
    timer.timeout.connect(cancel)
    timer.start(10)
    try:
        assert widget._run_godot_export(exporter, lambda parent, fn, **kwargs: fn()) is None
    finally:
        timer.stop()
        widget.close()
    assert len(reviewed) == 1
    assert files(exporter.output_dir) == before


@pytest.fixture
def qapp():
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_static_sprite_can_gain_animation_without_replacing_authored_scene(tmp_path, monkeypatch):
    from PIL import Image
    from spritesage.sprite_file import SpriteFile
    from spritesage import exporter as module

    monkeypatch.setattr(module, "remove_background_image", lambda image: image.convert("RGBA"))
    from spritesage import spritesheet

    monkeypatch.setattr(
        spritesheet,
        "remove_background_images",
        lambda images: [image.convert("RGBA") for image in images],
    )
    base = tmp_path / "base.png"
    Image.new("RGBA", (8, 8), (30, 40, 50, 128)).save(base)
    sprite = SpriteFile("static", "Hero", "", 8, 8, str(base), {})
    exporter = GodotSpriteExporter(sprite, str(tmp_path / "export"))
    exporter.export()
    scene = exporter.output_dir / "Hero.tscn"
    scene.write_text(
        scene.read_text()
        + '\nmetadata/game = {"health": 100}\n[node name="Hitbox" type="Area2D" parent="."]\ncollision_layer = 8\n'
    )
    sprite.animations["walk"] = Animation("walk", [str(base)], 7, False)
    before = files(exporter.output_dir)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert plan.updates and plan.file_diffs
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert 'metadata/game = {"health": 100}' in scene.read_text()
    assert "collision_layer = 8" in scene.read_text()
    assert 'type="AnimatedSprite2D"' in scene.read_text()
    assert (exporter.output_dir / "base.png").read_bytes() == before["base.png"][0]
    assert GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare().unchanged


def test_godot_only_animation_sharing_a_texture_keeps_its_pixels(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    selected = godot_text.fields(
        value, godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[2]
    )
    shared = selected["texture"].text(value)
    extra = godot_text.animations(value)["game-only"]
    resource.write_text(
        godot_text.patch(value, [(extra["frames"], '[{"duration": 1, "texture": ' + shared + "}]")])
    )
    replace_frame(sprite)
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    value = resource.read_text()
    target = godot_text.fields(
        value, godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[2]
    )["texture"].text(value)
    assert target != shared
    assert shared in godot_text.animations(value)["game-only"]["frames"].text(value)


def test_godot_reorder_then_second_update_keeps_timing_baseline_with_frame_identity(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    span = godot_text.animations(value)["attack"]["frames"]
    records = godot_text.items(value, span)
    resource.write_text(
        godot_text.patch(
            value, [(span, "[" + ",".join(s.text(value) for s in reversed(records)) + "]")]
        )
    )
    replace_frame(sprite)
    exporter.prepare().apply(allow_conflicts=True)
    sprite.animations["attack"].frame_durations[3] = 1.8
    plan = exporter.prepare()
    assert not plan.conflicts  # The first accepted export acknowledged the authored 3.5 hold.
    plan.apply(allow_conflicts=True)
    assert playback(resource, "attack")[2] == [1, 1, 1.44, 2, 1, 1]


def test_rename_and_art_change_together_preserve_authored_playback(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    replace_frame(sprite)
    sprite.animations["strike"] = sprite.animations.pop("attack")
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    assert playback(resource, "strike") == (8, True, [1, 1, 2, 3.5, 1, 1])


def test_animation_renamed_in_godot_keeps_name_and_playback_when_source_art_changes(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    change_setting(resource, "attack", "name", '&"authored-attack"')
    before = resource.read_bytes()
    replace_frame(sprite)
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    assert resource.read_bytes() == before
    assert playback(resource, "authored-attack") == (8, True, [1, 1, 2, 3.5, 1, 1])
    assert "attack" not in godot_text.animations(resource.read_text())
    sprite.animations["attack"].frame_durations[3] = 1.8
    plan = exporter.prepare()
    assert not plan.conflicts
    plan.apply(allow_conflicts=True)
    assert playback(resource, "authored-attack")[2] == [1, 1, 2, 1.44, 1, 1]


@pytest.mark.parametrize("edit", ["art", "fps"])
def test_bound_resource_outside_export_folder_keeps_authored_data(asset, tmp_path, edit):
    sprite, exporter = asset
    scene, canonical = author_game_data(exporter)
    (tmp_path / "project.godot").write_text("config_version=5\n")
    external = tmp_path / "authored_frames.tres"
    external.write_text(
        canonical.read_text().replace('path="Hero_sheet.png"', 'path="res://export/Hero_sheet.png"')
    )
    change_setting(external, "attack", "speed", "6")
    change_setting(external, "attack", "loop", "false")
    external.write_text(external.read_text() + 'metadata/external_game = {"health": 200}\n')
    scene.write_text(
        scene.read_text().replace('path="Hero_frames.tres"', 'path="res://authored_frames.tres"')
    )
    before_scene, before_external = scene.read_bytes(), external.read_bytes()
    if edit == "art":
        replace_frame(sprite)
    else:
        sprite.animations["attack"].fps = 12
    plan = exporter.prepare()
    plan.apply(allow_conflicts=True)
    assert external.read_bytes() == before_external
    if edit == "art":
        assert scene.read_bytes() == before_scene
    else:
        assert playback(canonical, "attack")[:2] == (12, False)
        assert 'metadata/external_game = {"health": 200}' in canonical.read_text()
    assert exporter.prepare().unchanged


def test_wrapped_sprite_updates_its_filter_without_touching_the_game_root(asset):
    sprite, exporter = asset
    scene, _ = author_game_data(exporter)
    value = scene.read_text()
    value = value.replace(
        '[node name="Hero" type="AnimatedSprite2D"]',
        '[node name="Player" type="CharacterBody2D"]\ntexture_filter = 3\nmetadata/health = 100\n\n[node name="Hero" type="AnimatedSprite2D" parent="."]',
    )
    scene.write_text(value)
    before = scene.read_bytes()
    sprite.pixel_art = False
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    plan.apply(allow_conflicts=True)
    assert scene.read_bytes() == before.replace(b"texture_filter = 1", b"texture_filter = 2")


@pytest.mark.parametrize("filename", ["Hero_frames.tres", "Hero_sheet.png"])
def test_interrupted_export_recovery_is_staged_and_cancel_changes_nothing(asset, filename):
    import base64
    import hashlib
    from spritesage.godot_export_transaction import PENDING

    _, exporter = asset
    resource = exporter.output_dir / filename
    original = resource.read_bytes()
    damaged = b"incomplete"
    resource.write_bytes(damaged)
    pending = {
        "version": 1,
        "before": {resource.name: base64.b64encode(original).decode()},
        "after": {resource.name: hashlib.sha256(damaged).hexdigest()},
    }
    (exporter.output_dir / PENDING).write_text(json.dumps(pending))
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert files(exporter.output_dir) == before
    assert plan.updates and plan.file_diffs
    plan.apply(allow_conflicts=True)
    assert resource.read_bytes() == original
    assert not (exporter.output_dir / PENDING).exists()


def test_project_recovery_retires_child_journal_only_after_acceptance(asset, tmp_path):
    import base64
    import hashlib
    from spritesage.exporter import GodotProjectExporter
    from spritesage.godot_export_transaction import PENDING

    sprite, _ = asset
    sprite.save(str(tmp_path / "hero.sprite"), str(tmp_path))
    project = GodotProjectExporter(str(tmp_path), str(tmp_path / "project-export"))
    project.export()
    resource = project.output_dir / "hero/Hero_frames.tres"
    original = resource.read_bytes()
    resource.write_bytes(b"incomplete")
    pending = {
        "version": 1,
        "before": {resource.name: base64.b64encode(original).decode()},
        "after": {resource.name: hashlib.sha256(b"incomplete").hexdigest()},
    }
    (resource.parent / PENDING).write_text(json.dumps(pending))
    before = files(project.output_dir)
    plan = project.prepare()
    assert files(project.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert resource.read_bytes() == original
    assert not (resource.parent / PENDING).exists()
    assert project.prepare().unchanged


def test_replaced_godot_texture_updates_that_frame_without_adding_a_frame(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    span = godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[2]
    record = span.text(value)
    fields = godot_text.fields(record, godot_text.Span(0, len(record)))
    record = godot_text.patch(record, [(fields["texture"], "null")])
    record = record[:1] + '"game_event": {"hit": "strike"}, ' + record[1:]
    resource.write_text(godot_text.patch(value, [(span, record)]))
    replace_frame(sprite)
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    value = resource.read_text()
    records = godot_text.items(value, godot_text.animations(value)["attack"]["frames"])
    assert len(records) == 6
    selected = godot_text.fields(value, records[2])
    assert selected["texture"].text(value) != "null"
    assert selected["game_event"].text(value) == '{"hit": "strike"}'


@pytest.mark.parametrize("shared", [False, True])
def test_new_atlas_cell_preserves_authored_texture_properties_and_metadata(asset, shared):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    frame = godot_text.fields(
        value, godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[2]
    )
    import re

    identifier = re.fullmatch(r'SubResource\("([^"]+)"\)', frame["texture"].text(value))[1]
    section = next(
        s
        for s in godot_text.sections(value)
        if s.kind == "sub_resource" and s.attributes.get("id") == json.dumps(identifier)
    )
    authored = 'margin = Rect2(0, 0, 2, 3)\nfilter_clip = true\nmetadata/texture_game = {"event": "strike", "ids": [4, 8]}\n'
    resource.write_text(
        godot_text.patch(
            value, [(godot_text.Span(section.body.start, section.body.start), authored)]
        )
    )
    if shared:
        value = resource.read_text()
        idle = godot_text.items(value, godot_text.animations(value)["idle"]["frames"])[0]
        idle_texture = godot_text.fields(value, idle)["texture"]
        resource.write_text(
            godot_text.patch(value, [(idle_texture, 'SubResource("' + identifier + '")')])
        )
        replace_frame(sprite)
    else:
        sprite.width = 16
    before = files(exporter.output_dir)
    plan = GodotSpriteExporter(sprite, str(exporter.output_dir)).prepare()
    assert files(exporter.output_dir) == before
    assert not any("texture mapping changed in Godot" in message for message in plan.conflicts)
    plan.apply(allow_conflicts=True)
    value = resource.read_text()
    frame = godot_text.fields(
        value, godot_text.items(value, godot_text.animations(value)["attack"]["frames"])[2]
    )
    new_identifier = re.fullmatch(r'SubResource\("([^"]+)"\)', frame["texture"].text(value))[1]
    section = next(
        s
        for s in godot_text.sections(value)
        if s.kind == "sub_resource" and s.attributes.get("id") == json.dumps(new_identifier)
    )
    if shared:
        assert new_identifier != identifier
        idle = godot_text.items(value, godot_text.animations(value)["idle"]["frames"])[0]
        assert (
            godot_text.fields(value, idle)["texture"].text(value)
            == 'SubResource("' + identifier + '")'
        )
    else:
        assert (
            new_identifier == identifier
        )  # A private atlas keeps its identity when its cell moves.
    assert authored in section.body.text(value)


def test_resaved_atlas_ids_and_frame_reorder_keep_identity_and_gameplay(asset):
    sprite, exporter = asset
    _, resource = author_game_data(exporter)
    value = resource.read_text()
    import re

    identifiers = re.findall(r'\[sub_resource type="AtlasTexture" id="([^"]+)"\]', value)
    for identifier in identifiers:
        value = value.replace(identifier, identifier + "_resaved")
    span = godot_text.animations(value)["attack"]["frames"]
    records = godot_text.items(value, span)
    value = godot_text.patch(
        value, [(span, "[" + ",".join(s.text(value) for s in reversed(records)) + "]")]
    )
    resource.write_text(value)
    before_resource = resource.read_bytes()
    replace_frame(sprite)
    before = files(exporter.output_dir)
    plan = exporter.prepare()
    assert files(exporter.output_dir) == before
    plan.apply(allow_conflicts=True)
    assert resource.read_bytes() == before_resource
    assert playback(resource, "attack") == (8, True, [1, 1, 3.5, 2, 1, 1])

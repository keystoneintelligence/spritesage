import json
import os
from typing import Any, cast

from PIL import Image

from spritesage import exporter as exporter_module
from spritesage import spritesheet
from spritesage.exporter import GodotProjectExporter, GodotSpriteExporter
from spritesage.sprite_file import Animation, SpriteFile
from spritesage.spritesheet import SpriteSheetGenerator


def test_sprite_file_defaults_to_legacy_base_image_playback(tmp_path):
    base = tmp_path / "base.png"
    frame = tmp_path / "frame.png"
    data = {
        "uuid": "legacy",
        "name": "Legacy",
        "description": "",
        "width": 16,
        "height": 16,
        "base_image": base.name,
        "animations": {"walk": [frame.name]},
    }

    sprite = SpriteFile.from_dict(data, str(tmp_path))

    assert sprite.include_base_image_in_animations is True
    assert sprite.get_animation_playback_frames("walk") == [str(base), str(frame)]


def test_sprite_file_persists_disabled_base_image_playback(tmp_path):
    base = tmp_path / "base.png"
    frame = tmp_path / "frame.png"
    sprite = SpriteFile(
        uuid="model",
        name="Model",
        description="",
        width=16,
        height=16,
        base_image=str(base),
        animations={"walk": Animation(name="walk", frames=[str(frame)])},
        include_base_image_in_animations=False,
    )

    sprite_path = tmp_path / "model.sprite"
    sprite.save(str(sprite_path), str(tmp_path))
    saved = json.loads(sprite_path.read_text(encoding="utf-8"))
    loaded = SpriteFile.from_json(str(sprite_path), str(tmp_path))

    assert saved["include_base_image_in_animations"] is False
    assert loaded.get_animation_playback_frames("walk") == [str(frame)]


def test_sheet_and_godot_export_respect_base_image_playback_setting(tmp_path, monkeypatch):
    base = tmp_path / "base.png"
    frame_a = tmp_path / "frame_a.png"
    frame_b = tmp_path / "frame_b.png"
    for path in (base, frame_a, frame_b):
        Image.new("RGBA", (8, 8)).save(path)

    for include_base, expected_count in ((True, 3), (False, 2)):
        sprite = SpriteFile(
            uuid=f"sprite-{include_base}",
            name=f"Sprite{include_base}",
            description="",
            width=8,
            height=8,
            base_image=str(base),
            animations={"walk": Animation(name="walk", frames=[str(frame_a), str(frame_b)])},
            include_base_image_in_animations=include_base,
        )
        generator = SpriteSheetGenerator(sprite)
        expected_paths = [str(frame_a), str(frame_b)]
        if include_base:
            expected_paths.insert(0, str(base))
        assert generator.get_all_frame_paths() == expected_paths

        output_dir = tmp_path / f"export_{include_base}"
        exporter = GodotSpriteExporter(sprite, str(output_dir))
        exporter.export()

        tres = (output_dir / f"{sprite.name}_frames.tres").read_text(encoding="utf-8")
        assert tres.count('[sub_resource type="AtlasTexture"') == expected_count
        assert tres.count('"texture": SubResource') == expected_count

        sheet_path = output_dir / f"{sprite.name}_sheet.png"
        assert sheet_path.is_file()
        assert os.path.getsize(sheet_path) > 0


def test_project_exporter_exports_all_project_sprites(tmp_path, monkeypatch):
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    output_dir = tmp_path / "exports" / "project"
    sprite_data = {
        "uuid": "sprite",
        "name": "Hero",
        "description": "",
        "width": 8,
        "height": 8,
        "base_image": "",
        "animations": {},
    }
    (tmp_path / "hero.sprite").write_text(json.dumps(sprite_data), encoding="utf-8")
    nested_sprite = dict(sprite_data, uuid="nested", name="Villain")
    (nested_dir / "villain.sprite").write_text(json.dumps(nested_sprite), encoding="utf-8")

    exporter_calls = []

    class FakeSpriteExporter:
        def __init__(self, sprite_file, output_dir, progress_callback=None):
            self.progress_callback = progress_callback
            exporter_calls.append((sprite_file.name, os.path.relpath(output_dir, str(tmp_path))))

        def export(self):
            assert self.progress_callback is not None
            self.progress_callback(1, 2, "Created alpha channels")
            return None

    monkeypatch.setattr(exporter_module, "GodotSpriteExporter", FakeSpriteExporter)
    progress = []

    exported_dirs = GodotProjectExporter(
        project_dir=str(tmp_path),
        output_dir=str(output_dir),
        progress_callback=lambda current, total, detail: progress.append((current, total, detail)),
    ).export()

    assert exporter_calls == [
        ("Hero", os.path.join("exports", "project", "hero")),
        ("Villain", os.path.join("exports", "project", "nested", "villain")),
    ]
    assert [os.path.relpath(path, str(tmp_path)) for path in exported_dirs] == [
        os.path.join("exports", "project", "hero"),
        os.path.join("exports", "project", "nested", "villain"),
    ]
    assert progress[0] == (0, 2, "Preparing 2 sprites for Godot export")
    assert (
        0,
        2,
        "Exporting hero.sprite: Created alpha channels (1 of 2 frames)",
    ) in progress
    assert (
        1,
        2,
        "Exporting nested/villain.sprite: Created alpha channels (1 of 2 frames)",
    ) in progress
    assert progress[-1] == (2, 2, "Exported nested/villain.sprite")


def test_spritesheet_preserves_frames_with_meaningful_alpha(tmp_path, monkeypatch):
    frame = tmp_path / "alpha_frame.png"
    image = Image.new("RGBA", (8, 8), cast(Any, (0, 255, 0, 0)))
    for x in range(2, 6):
        for y in range(2, 6):
            image.putpixel((x, y), (120, 80, 40, 255))
    image.save(frame)

    def fail_remove_background_images(_images):
        raise AssertionError("alpha extraction should not run for meaningful frame alpha")

    monkeypatch.setattr(spritesheet, "remove_background_images", fail_remove_background_images)

    sprite = SpriteFile(
        uuid="sprite-alpha",
        name="SpriteAlpha",
        description="",
        width=8,
        height=8,
        base_image="",
        animations={"idle": Animation(name="idle", frames=[str(frame)])},
        include_base_image_in_animations=False,
    )
    output_path = tmp_path / "alpha_sheet.png"

    SpriteSheetGenerator(sprite).create_spritesheet(str(output_path))

    result = Image.open(output_path).convert("RGBA")
    assert result.getpixel((0, 0)) == (0, 0, 0, 0)
    assert result.getpixel((3, 3)) == (120, 80, 40, 255)


def test_spritesheet_extracts_alpha_per_opaque_frame(tmp_path, monkeypatch):
    alpha_frame = tmp_path / "alpha_frame.png"
    opaque_frame = tmp_path / "opaque_frame.png"

    Image.new("RGBA", (8, 8), cast(Any, (0, 0, 0, 0))).save(alpha_frame)
    Image.new("RGBA", (8, 8), cast(Any, (255, 255, 255, 255))).save(opaque_frame)

    calls = []

    def fake_remove_background_images(images):
        calls.append([image.size for image in images])
        outputs = []
        for image in images:
            output = image.copy()
            for x in range(output.width):
                for y in range(output.height):
                    output.putpixel((x, y), (10, 20, 30, 0 if x < 4 else 255))
            outputs.append(output)
        return outputs

    monkeypatch.setattr(spritesheet, "remove_background_images", fake_remove_background_images)

    sprite = SpriteFile(
        uuid="sprite-mixed",
        name="SpriteMixed",
        description="",
        width=8,
        height=8,
        base_image="",
        animations={"idle": Animation(name="idle", frames=[str(alpha_frame), str(opaque_frame)])},
        include_base_image_in_animations=False,
    )
    progress = []
    output_path = tmp_path / "mixed_sheet.png"

    SpriteSheetGenerator(sprite).create_spritesheet(
        str(output_path),
        progress_callback=lambda current, total, detail: progress.append((current, total, detail)),
    )

    assert calls == [[(8, 8)]]
    assert (0, 1, "Preparing alpha extraction for 1 of 2 frames") in progress
    assert (1, 1, "Created alpha channels for 1 of 1 frames") in progress
    assert progress[-1] == (1, 1, "Saved sprite sheet with 2 frames")
    result = Image.open(output_path).convert("RGBA")
    assert result.getpixel((8, 0)) == (0, 0, 0, 0)
    assert result.getpixel((12, 0)) == (10, 20, 30, 255)

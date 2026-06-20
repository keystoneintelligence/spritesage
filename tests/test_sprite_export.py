import json
import os

from PIL import Image

from spritesage import spritesheet
from spritesage.exporter import GodotSpriteExporter
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

    monkeypatch.setattr(spritesheet, "remove_background", lambda source, target: None)

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

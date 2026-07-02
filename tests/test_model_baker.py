import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from spritesage.model_baker import godot_exporter, service, vtk_baker
from spritesage.model_baker import (
    ModelBakeConfig,
    available_view_sets,
    bake_model_to_sprite_project,
    write_sprite_file_from_manifest,
)
from spritesage.model_baker.animations import (
    AnimationClip,
    frame_times,
    rest_clip,
    select_base_pose_clip,
    select_clips,
)
from spritesage.model_baker.cameras import (
    ViewSpec,
    apply_camera,
    bounds_center_radius,
    camera_direction,
    resolve_view_set,
)
from spritesage.model_baker.godot_exporter import export_godot_sprite
from spritesage.model_baker.sheet import make_contact_sheet
from spritesage.model_baker.stylize import apply_style, pixelate
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


def test_frame_times_includes_start_and_caps_to_duration():
    assert frame_times(duration=0.26, fps=10) == [0.0, 0.1, 0.2]
    assert frame_times(duration=0.25, fps=8, max_frames=2) == [0.0, 0.125]
    assert frame_times(duration=0, fps=8) == [0.0]

    with pytest.raises(ValueError, match="fps"):
        frame_times(duration=1, fps=0)
    with pytest.raises(ValueError, match="max_frames"):
        frame_times(duration=1, fps=8, max_frames=0)


def test_select_clips_defaults_filters_by_name_or_index_and_reports_unknown():
    idle = AnimationClip(index=0, name="Idle", duration=1.0)
    walk = AnimationClip(index=1, name="Walk", duration=2.0)

    assert select_clips([], None) == [rest_clip()]
    assert select_clips([idle, walk], None) == [idle, walk]
    assert select_clips([idle, walk], ["walk", "0"]) == [walk, idle]

    with pytest.raises(ValueError, match="Unknown animation 'run'.*Idle, Walk"):
        select_clips([idle, walk], ["run"])


def test_camera_helpers_resolve_bounds_direction_and_apply_to_renderer():
    assert resolve_view_set("top")[0].name == "top"
    with pytest.raises(ValueError, match="Unknown view set 'missing'"):
        resolve_view_set("missing")

    center, radius = bounds_center_radius((0, 2, 10, 14, -1, 1))
    np.testing.assert_allclose(center, [1, 12, 0])
    assert radius == pytest.approx(np.linalg.norm([2, 4, 2]) * 0.5)

    direction = camera_direction(ViewSpec("front_right", 45, 0))
    np.testing.assert_allclose(direction, [np.sqrt(0.5), 0, np.sqrt(0.5)], atol=1e-6)

    class FakeCamera:
        def __init__(self):
            self.position = None
            self.focal_point = None
            self.view_up = None
            self.parallel_projection = None
            self.parallel_scale = None

        def SetPosition(self, *values):
            self.position = values

        def SetFocalPoint(self, *values):
            self.focal_point = values

        def SetViewUp(self, *values):
            self.view_up = values

        def SetParallelProjection(self, value):
            self.parallel_projection = value

        def SetParallelScale(self, value):
            self.parallel_scale = value

    class FakeRenderer:
        def __init__(self):
            self.camera = FakeCamera()
            self.reset = False

        def GetActiveCamera(self):
            return self.camera

        def ResetCameraClippingRange(self):
            self.reset = True

    renderer = FakeRenderer()
    apply_camera(renderer, (0, 2, 0, 2, 0, 2), ViewSpec("top", 0, 89), zoom=2)

    assert renderer.camera.focal_point == (1.0, 1.0, 1.0)
    assert renderer.camera.view_up == (0.0, 0.0, -1.0)
    assert renderer.camera.parallel_projection is True
    assert renderer.camera.parallel_scale == pytest.approx((np.sqrt(3) * 1.15) / 2)
    assert renderer.reset is True

    with pytest.raises(ValueError, match="zoom"):
        apply_camera(renderer, (0, 1, 0, 1, 0, 1), ViewSpec("front", 0, 0), zoom=0)


def test_apply_style_converts_to_rgba_pixelates_and_rejects_unknown_style():
    image = Image.new("RGB", (4, 4), "white")
    image.putpixel((0, 0), (0, 0, 0))

    unchanged = apply_style(image, "none")
    assert unchanged.mode == "RGBA"
    assert unchanged.size == (4, 4)

    pixelated = apply_style(image, "pixel", pixel_size=2)
    assert pixelated.mode == "RGBA"
    assert pixelated.size == (4, 4)
    assert pixelated.getpixel((0, 0)) != unchanged.getpixel((0, 0))
    assert pixelated.getpixel((0, 0)) == pixelated.getpixel((1, 1))

    assert pixelate(unchanged, pixel_size=1) is unchanged
    with pytest.raises(ValueError, match="Unknown style 'oil'"):
        apply_style(image, "oil")


def test_make_contact_sheet_preserves_view_order_and_resizes_frames(tmp_path):
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    green = tmp_path / "green.png"
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(red)
    Image.new("RGBA", (1, 1), (0, 0, 255, 255)).save(blue)
    Image.new("RGBA", (2, 2), (0, 255, 0, 255)).save(green)

    output = make_contact_sheet(
        {"front": [red, blue], "back": [green]},
        tmp_path / "nested" / "sheet.png",
        cell_size=2,
    )

    sheet = Image.open(output).convert("RGBA")
    assert sheet.size == (4, 4)
    assert sheet.getpixel((0, 0)) == (255, 0, 0, 255)
    assert sheet.getpixel((2, 0)) == (0, 0, 255, 255)
    assert sheet.getpixel((0, 2)) == (0, 255, 0, 255)


def test_export_godot_sprite_writes_safe_scene_and_sprite_frames(tmp_path, monkeypatch):
    sheet = tmp_path / "Walk Sheet.png"
    sheet.write_bytes(b"png")
    uid_values = iter(["uid://frames", "uid://scene", "uid://sheet"])
    monkeypatch.setattr(godot_exporter, "_uid", lambda: next(uid_values))

    result = export_godot_sprite(
        output_dir=tmp_path,
        sprite_name="Hero Knight!",
        animations=[
            {
                "name": "Walk Cycle",
                "sheet": sheet,
                "times": [0.0, 0.125],
                "views": {"front/right": [], "dead": []},
            }
        ],
        cell_size=16,
        fps=8,
    )

    assert result.output_dir == tmp_path / "godot"
    assert result.sprite_frames_path.name == "Hero_Knight__frames.tres"
    assert result.scene_path.name == "Hero_Knight_.tscn"

    tres = result.sprite_frames_path.read_text(encoding="utf-8")
    scene = result.scene_path.read_text(encoding="utf-8")
    assert 'path="../Walk Sheet.png"' in tres
    assert 'id="AtlasTexture_Walk_Cycle_front_right_001"' in tres
    assert "region = Rect2(16, 0, 16, 16)" in tres
    assert '"name": &"Walk_Cycle_dead"' in tres
    assert '"loop": true' in tres
    assert 'animation = &"Walk_Cycle_front_right"' in scene


def test_vtk_baker_remove_background_and_safe_name_are_pure():
    rgba = np.array(
        [
            [[0, 255, 0, 255], [4, 255, 0, 255]],
            [[10, 0, 0, 255], [0, 254, 1, 255]],
        ],
        dtype=np.uint8,
    )

    result = vtk_baker._remove_background(rgba, (0, 255, 0), threshold=2)

    assert result[0, 0, 3] == 0
    assert result[1, 1, 3] == 0
    assert result[0, 1, 3] == 255
    assert vtk_baker._safe_name("Walk Cycle!") == "Walk_Cycle_"
    assert vtk_baker._safe_name("") == "unnamed"


def test_vtk_baker_bakes_static_model_as_idle_animation(tmp_path, monkeypatch):
    model_path = tmp_path / "static.glb"
    model_path.write_bytes(b"placeholder")
    output_dir = tmp_path / "bake"
    render_calls = []

    class FakeSkinnedGltf:
        def __init__(self, model_path):
            raise ValueError("No skinned mesh node found")

    class FakeMesh:
        def GetBounds(self):
            return (0, 1, 0, 1, 0, 1)

    class FakeStaticGltf:
        def __init__(self, model_path):
            self.model_path = Path(model_path)

        def deformed_points(self, animation_index, time_value):
            render_calls.append((animation_index, time_value))
            return np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)

        def to_polydata(self, points):
            return FakeMesh()

    class FakeRenderWindow:
        def __init__(self):
            self.finalized = False

        def Finalize(self):
            self.finalized = True

    def fake_render_frame(**kwargs):
        image = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        output_path = kwargs["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)

    monkeypatch.setattr(vtk_baker, "inspect_animations", lambda path: [])
    monkeypatch.setattr(vtk_baker, "SkinnedGltf", FakeSkinnedGltf)
    monkeypatch.setattr(vtk_baker, "StaticGltf", FakeStaticGltf)
    monkeypatch.setattr(vtk_baker, "extract_texture_from_gltf_or_glb", lambda path: None)
    monkeypatch.setattr(
        vtk_baker, "_create_renderer", lambda config: (FakeRenderWindow(), object())
    )
    monkeypatch.setattr(vtk_baker, "_render_frame", fake_render_frame)

    result = vtk_baker.bake(
        vtk_baker.BakeConfig(
            model_path=model_path,
            output_dir=output_dir,
            view_set="front3",
            size=2,
        )
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base_image"] == str(output_dir / "base" / "front.png")
    assert manifest["animations"][0]["name"] == "idle"
    assert manifest["animations"][0]["times"] == [0.0]
    assert set(manifest["animations"][0]["views"]) == {"front", "left", "right"}
    assert result.frame_count == 3
    assert render_calls == [(-1, 0.0), (-1, 0.0)]


def test_static_gltf_loads_triangle_mesh_with_node_transform(tmp_path):
    from pygltflib import (
        Accessor,
        Asset,
        Attributes,
        Buffer,
        BufferView,
        GLTF2,
        Mesh,
        Node,
        Primitive,
        Scene,
    )

    from spritesage.model_baker.skinned_gltf import StaticGltf

    model_path = tmp_path / "triangle.glb"
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    uvs = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32)
    indices = np.array([0, 1, 2], dtype=np.uint16)
    blob = positions.tobytes() + uvs.tobytes() + indices.tobytes() + b"\0\0"

    gltf = GLTF2(
        asset=Asset(version="2.0"),
        scene=0,
        scenes=[Scene(nodes=[0])],
        nodes=[Node(mesh=0, translation=[2, 3, 4])],
        meshes=[
            Mesh(
                primitives=[
                    Primitive(
                        attributes=Attributes(POSITION=0, TEXCOORD_0=1),
                        indices=2,
                    )
                ]
            )
        ],
        buffers=[Buffer(byteLength=len(blob))],
        bufferViews=[
            BufferView(buffer=0, byteOffset=0, byteLength=positions.nbytes),
            BufferView(buffer=0, byteOffset=positions.nbytes, byteLength=uvs.nbytes),
            BufferView(
                buffer=0,
                byteOffset=positions.nbytes + uvs.nbytes,
                byteLength=indices.nbytes,
            ),
        ],
        accessors=[
            Accessor(
                bufferView=0,
                componentType=5126,
                count=3,
                type="VEC3",
                min=[0, 0, 0],
                max=[1, 1, 0],
            ),
            Accessor(bufferView=1, componentType=5126, count=3, type="VEC2"),
            Accessor(bufferView=2, componentType=5123, count=3, type="SCALAR"),
        ],
    )
    gltf.set_binary_blob(blob)
    gltf.save_binary(str(model_path))

    model = StaticGltf(model_path)

    np.testing.assert_allclose(
        model.deformed_points(-1, 0.0),
        [[2, 3, 4], [3, 3, 4], [2, 4, 4]],
    )
    np.testing.assert_allclose(model.texture_coordinates, uvs)
    np.testing.assert_array_equal(model.indices, [0, 1, 2])
    with pytest.raises(ValueError, match="Static mesh animation sampling"):
        model.deformed_points(0, 0.0)


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


def test_bake_model_to_sprite_project_success_maps_config_copies_and_overwrites(
    tmp_path,
    monkeypatch,
):
    model_path = tmp_path / "source models" / "Hero Knight.glb"
    model_path.parent.mkdir()
    model_path.write_bytes(b"glb")
    project_dir = tmp_path / "project"
    output_dir = project_dir / "custom" / "bake"
    output_dir.mkdir(parents=True)
    (output_dir / "old.txt").write_text("replaceable", encoding="utf-8")

    captured_renderer_configs = []
    manifest_path = output_dir / "manifest.json"
    sheet_path = output_dir / "sheets" / "walk.png"
    godot_frames_path = output_dir / "godot" / "hero_frames.tres"
    godot_scene_path = output_dir / "godot" / "hero.tscn"

    def fake_bake(renderer_config):
        captured_renderer_configs.append(renderer_config)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            manifest_path=manifest_path,
            sheet_paths=[sheet_path],
            godot_sprite_frames_path=godot_frames_path,
            godot_scene_path=godot_scene_path,
        )

    def fake_write_sprite_file_from_manifest(
        manifest_path_arg,
        *,
        sprite_path,
        project_dir: Path,
        sprite_name,
        width,
        height,
    ):
        assert manifest_path_arg == manifest_path
        assert sprite_path == project_dir.resolve() / "Hero_Knight.sprite"
        assert project_dir == project_dir.resolve()
        assert sprite_name == "Hero Knight"
        assert width == 128
        assert height == 128
        sprite_path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(frame_count=7, animation_names=("Walk_front",))

    monkeypatch.setattr(
        service,
        "write_sprite_file_from_manifest",
        fake_write_sprite_file_from_manifest,
    )
    monkeypatch.setattr(vtk_baker, "bake", fake_bake)

    result = bake_model_to_sprite_project(
        ModelBakeConfig(
            model_path=model_path,
            project_dir=project_dir,
            sprite_name="Hero Knight",
            output_subdir=Path("custom") / "bake",
            view_set="side2",
            fps=12,
            frame_size=128,
            zoom=1.5,
            style="pixel",
            pixel_size=3,
            selected_animations=("Walk", "Idle"),
            max_frames=4,
            overwrite=True,
        )
    )

    renderer_config = captured_renderer_configs[0]
    assert renderer_config.model_path == output_dir.resolve() / "source" / model_path.name
    assert renderer_config.output_dir == output_dir.resolve()
    assert renderer_config.sprite_name == "Hero_Knight"
    assert renderer_config.view_set == "side2"
    assert renderer_config.fps == 12.0
    assert renderer_config.size == 128
    assert renderer_config.zoom == 1.5
    assert renderer_config.style == "pixel"
    assert renderer_config.pixel_size == 3
    assert renderer_config.selected_animations == ["Walk", "Idle"]
    assert renderer_config.max_frames == 4
    assert renderer_config.model_path.read_bytes() == b"glb"

    assert result.project_dir == project_dir.resolve()
    assert result.sprite_path == project_dir.resolve() / "Hero_Knight.sprite"
    assert result.bake_output_dir == output_dir.resolve()
    assert result.manifest_path == manifest_path
    assert result.source_model_path == renderer_config.model_path
    assert result.sheet_paths == (sheet_path,)
    assert result.godot_sprite_frames_path == godot_frames_path
    assert result.godot_scene_path == godot_scene_path
    assert result.frame_count == 7
    assert result.animation_names == ("Walk_front",)


def test_bake_model_to_sprite_project_can_skip_source_model_copy(tmp_path, monkeypatch):
    model_path = tmp_path / "hero.glb"
    model_path.write_bytes(b"glb")
    project_dir = tmp_path / "project"
    captured_renderer_configs = []

    def fake_bake(renderer_config):
        captured_renderer_configs.append(renderer_config)
        return SimpleNamespace(
            manifest_path=project_dir / "sprites" / "hero" / "manifest.json",
            sheet_paths=[],
            godot_sprite_frames_path=None,
            godot_scene_path=None,
        )

    monkeypatch.setattr(vtk_baker, "bake", fake_bake)
    monkeypatch.setattr(
        service,
        "write_sprite_file_from_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            frame_count=1,
            animation_names=("Idle_front",),
        ),
    )

    result = bake_model_to_sprite_project(
        ModelBakeConfig(
            model_path=model_path,
            project_dir=project_dir,
            copy_source_model=False,
        )
    )

    assert captured_renderer_configs[0].model_path == model_path.resolve()
    assert result.source_model_path is None

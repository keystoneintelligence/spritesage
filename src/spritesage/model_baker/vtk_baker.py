from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkRenderer,
    vtkRenderWindow,
    vtkWindowToImageFilter,
)
import vtkmodules.vtkRenderingFreeType  # noqa: F401 - registers text rendering overrides
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401 - registers the OpenGL render window
from vtkmodules.util.numpy_support import vtk_to_numpy

from .animations import (
    AnimationClip,
    frame_times,
    inspect_animations,
    select_base_pose_clip,
    select_clips,
)
from .cameras import ViewSpec, apply_camera, resolve_view_set
from .godot_exporter import export_godot_sprite
from .mesh_io import extract_texture_from_gltf_or_glb
from .sheet import make_contact_sheet
from .skinned_gltf import SkinnedGltf, StaticGltf
from .stylize import apply_style


@dataclass(frozen=True)
class BakeConfig:
    model_path: Path
    output_dir: Path
    sprite_name: str | None = None
    view_set: str = "iso8"
    fps: float = 8.0
    size: int = 256
    zoom: float = 1.0
    style: str = "none"
    pixel_size: int = 4
    selected_animations: list[str] | None = None
    max_frames: int | None = None
    background_rgb: tuple[int, int, int] = (0, 255, 0)
    background_threshold: int = 2


@dataclass(frozen=True)
class BakeResult:
    output_dir: Path
    manifest_path: Path
    sheet_paths: list[Path] = field(default_factory=list)
    godot_sprite_frames_path: Path | None = None
    godot_scene_path: Path | None = None
    frame_count: int = 0


def bake(config: BakeConfig) -> BakeResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    frame_root = config.output_dir / "frames"
    sheet_root = config.output_dir / "sheets"
    frame_root.mkdir(parents=True, exist_ok=True)
    sheet_root.mkdir(parents=True, exist_ok=True)

    views = resolve_view_set(config.view_set)
    all_clips = inspect_animations(config.model_path)
    clips = select_clips(all_clips, config.selected_animations)

    model = _load_model(config.model_path)
    if isinstance(model, StaticGltf):
        clips = [AnimationClip(index=-1, name="idle", duration=0.0)]
    texture = extract_texture_from_gltf_or_glb(config.model_path)
    render_window, renderer = _create_renderer(config)

    manifest: dict[str, Any] = {
        "model": str(config.model_path),
        "view_set": config.view_set,
        "fps": config.fps,
        "size": config.size,
        "zoom": config.zoom,
        "style": config.style,
        "base_image": None,
        "animations": [],
    }

    sheet_paths: list[Path] = []
    total_frames = 0
    try:
        base_view = views[0]
        base_path = config.output_dir / "base" / f"{base_view.name}.png"
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_clip = select_base_pose_clip(all_clips)
        base_animation_index = base_clip.index if base_clip is not None else -1
        base_points = model.deformed_points(base_animation_index, 0.0)
        base_mesh = model.to_polydata(base_points)
        _render_frame(
            render_window=render_window,
            renderer=renderer,
            mesh=base_mesh,
            texture=texture,
            bounds=base_mesh.GetBounds(),
            view=base_view,
            output_path=base_path,
            config=config,
        )
        manifest["base_image"] = str(base_path)
        manifest["base_view"] = base_view.name
        manifest["base_pose"] = {
            "source": "animation" if base_clip is not None else "bind_pose",
            "animation": base_clip.name if base_clip is not None else None,
            "time": 0.0,
        }

        for clip in clips:
            times = frame_times(clip.duration, config.fps, config.max_frames)
            frames_by_view: dict[str, list[Path]] = {view.name: [] for view in views}

            for frame_index, time_value in enumerate(times):
                points = model.deformed_points(clip.index, float(time_value))
                mesh = model.to_polydata(points)
                bounds = mesh.GetBounds()
                for view in views:
                    output_path = (
                        frame_root
                        / _safe_name(clip.name)
                        / view.name
                        / f"frame_{frame_index:03d}.png"
                    )
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    _render_frame(
                        render_window=render_window,
                        renderer=renderer,
                        mesh=mesh,
                        texture=texture,
                        bounds=bounds,
                        view=view,
                        output_path=output_path,
                        config=config,
                    )
                    frames_by_view[view.name].append(output_path)
                    total_frames += 1

            sheet_path = sheet_root / f"{_safe_name(clip.name)}.png"
            make_contact_sheet(frames_by_view, sheet_path, config.size)
            sheet_paths.append(sheet_path)

            manifest["animations"].append(
                {
                    "name": clip.name,
                    "index": clip.index,
                    "duration": clip.duration,
                    "times": times,
                    "views": {
                        view_name: [str(path) for path in paths]
                        for view_name, paths in frames_by_view.items()
                    },
                    "sheet": str(sheet_path),
                }
            )
    finally:
        render_window.Finalize()

    godot_export = export_godot_sprite(
        output_dir=config.output_dir,
        sprite_name=f"{_safe_name(config.sprite_name or config.model_path.stem)}_{config.view_set}",
        animations=manifest["animations"],
        cell_size=config.size,
        fps=config.fps,
    )
    manifest["godot"] = {
        "sprite_frames": str(godot_export.sprite_frames_path),
        "scene": str(godot_export.scene_path),
    }

    manifest_path = config.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return BakeResult(
        output_dir=config.output_dir,
        manifest_path=manifest_path,
        sheet_paths=sheet_paths,
        godot_sprite_frames_path=godot_export.sprite_frames_path,
        godot_scene_path=godot_export.scene_path,
        frame_count=total_frames,
    )


def _load_model(model_path: str | Path) -> SkinnedGltf | StaticGltf:
    try:
        return SkinnedGltf(model_path)
    except ValueError as exc:
        if str(exc) != "No skinned mesh node found":
            raise
        return StaticGltf(model_path)


def _create_renderer(config: BakeConfig) -> tuple[vtkRenderWindow, vtkRenderer]:
    renderer = vtkRenderer()
    render_window = vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.SetSize(int(config.size), int(config.size))
    render_window.SetMultiSamples(0)
    render_window.SetAlphaBitPlanes(1)
    render_window.AddRenderer(renderer)
    r, g, b = [channel / 255.0 for channel in config.background_rgb]
    renderer.SetBackground(r, g, b)
    return render_window, renderer


def _render_frame(
    *,
    render_window,
    renderer,
    mesh,
    texture,
    bounds,
    view: ViewSpec,
    output_path: Path,
    config: BakeConfig,
) -> None:
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(mesh)
    mapper.ScalarVisibilityOff()

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetInterpolationToPhong()
    if texture is not None:
        actor.SetTexture(texture)
        actor.GetProperty().SetColor(1.0, 1.0, 1.0)
    else:
        actor.GetProperty().SetColor(0.7, 0.7, 0.7)

    renderer.RemoveAllViewProps()
    renderer.AddActor(actor)
    apply_camera(renderer, bounds, view, zoom=config.zoom)
    render_window.Render()
    rgba = _capture_rgba(render_window)
    rgba = _remove_background(rgba, config.background_rgb, config.background_threshold)
    image = Image.fromarray(rgba, mode="RGBA")
    image = apply_style(image, style=config.style, pixel_size=config.pixel_size)
    image.save(output_path)


def _capture_rgba(render_window) -> np.ndarray:
    capture = vtkWindowToImageFilter()
    capture.SetInput(render_window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()

    image_data = capture.GetOutput()
    width, height, _depth = image_data.GetDimensions()
    scalars = image_data.GetPointData().GetScalars()
    if scalars is None:
        raise RuntimeError("VTK returned no pixels")

    array = vtk_to_numpy(scalars).reshape(height, width, 4)
    return np.flipud(array).astype(np.uint8)


def _remove_background(
    rgba: np.ndarray,
    background_rgb: tuple[int, int, int],
    threshold: int,
) -> np.ndarray:
    out = rgba.copy()
    rgb = out[:, :, :3].astype(np.int16)
    bg = np.array(background_rgb, dtype=np.int16)
    delta = np.abs(rgb - bg)
    mask = np.all(delta <= int(threshold), axis=2)
    out[mask, 3] = 0
    return out


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    return safe or "unnamed"

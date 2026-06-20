from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Sequence

from .sprite_writer import SpriteWriteResult, write_sprite_file_from_manifest

SUPPORTED_MODEL_EXTENSIONS = {".glb"}
SUPPORTED_STYLES = {"none", "pixel"}


@dataclass(frozen=True)
class ModelAnimation:
    index: int
    name: str
    duration: float


@dataclass(frozen=True)
class ModelBakeConfig:
    model_path: Path
    project_dir: Path
    sprite_name: str | None = None
    output_subdir: str | Path | None = None
    view_set: str = "iso8"
    fps: float = 8.0
    frame_size: int = 256
    zoom: float = 1.0
    style: str = "none"
    pixel_size: int = 4
    selected_animations: Sequence[str] | None = None
    max_frames: int | None = None
    copy_source_model: bool = True
    overwrite: bool = False


@dataclass(frozen=True)
class ModelBakeResult:
    project_dir: Path
    sprite_path: Path
    bake_output_dir: Path
    manifest_path: Path
    source_model_path: Path | None
    sheet_paths: tuple[Path, ...]
    godot_sprite_frames_path: Path | None
    godot_scene_path: Path | None
    frame_count: int
    animation_names: tuple[str, ...]


def available_view_sets() -> tuple[str, ...]:
    from .cameras import VIEW_SETS

    return tuple(sorted(VIEW_SETS))


def inspect_model_animations(model_path: str | Path) -> tuple[ModelAnimation, ...]:
    try:
        from .animations import inspect_animations
    except ModuleNotFoundError as exc:
        if exc.name == "pygltflib":
            raise RuntimeError(_optional_dependency_message()) from exc
        raise

    return tuple(
        ModelAnimation(index=clip.index, name=clip.name, duration=clip.duration)
        for clip in inspect_animations(model_path)
    )


def bake_model_to_sprite_project(config: ModelBakeConfig) -> ModelBakeResult:
    """Bake a GLB model into project-local frames and a normal `.sprite` file."""
    _validate_config(config)

    project_dir = Path(config.project_dir).resolve()
    model_path = Path(config.model_path).resolve()
    sprite_name = config.sprite_name or model_path.stem
    slug = _safe_asset_name(sprite_name)
    bake_output_dir = _resolve_output_dir(project_dir, slug, config.output_subdir)
    sprite_path = project_dir / f"{slug}.sprite"

    if sprite_path.exists() and not config.overwrite:
        raise FileExistsError(f"Sprite already exists: {sprite_path}")
    if (
        bake_output_dir.exists()
        and _directory_has_entries(bake_output_dir)
        and not config.overwrite
    ):
        raise FileExistsError(f"Bake output directory already has files: {bake_output_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)
    bake_output_dir.mkdir(parents=True, exist_ok=True)
    source_model_path = (
        _copy_source_model(model_path, bake_output_dir) if config.copy_source_model else None
    )
    render_model_path = source_model_path or model_path

    try:
        from .vtk_baker import BakeConfig as RendererBakeConfig
        from .vtk_baker import bake as bake_frames
    except ModuleNotFoundError as exc:
        if exc.name in {"pygltflib", "vtkmodules"}:
            raise RuntimeError(_optional_dependency_message()) from exc
        raise

    renderer_result = bake_frames(
        RendererBakeConfig(
            model_path=render_model_path,
            output_dir=bake_output_dir,
            sprite_name=slug,
            view_set=config.view_set,
            fps=float(config.fps),
            size=int(config.frame_size),
            zoom=float(config.zoom),
            style=config.style,
            pixel_size=int(config.pixel_size),
            selected_animations=(
                list(config.selected_animations) if config.selected_animations is not None else None
            ),
            max_frames=config.max_frames,
        )
    )

    write_result = write_sprite_file_from_manifest(
        renderer_result.manifest_path,
        sprite_path=sprite_path,
        project_dir=project_dir,
        sprite_name=sprite_name,
        width=config.frame_size,
        height=config.frame_size,
    )
    return _build_result(
        project_dir=project_dir,
        sprite_path=sprite_path,
        bake_output_dir=bake_output_dir,
        source_model_path=source_model_path,
        renderer_result=renderer_result,
        write_result=write_result,
    )


def _validate_config(config: ModelBakeConfig) -> None:
    model_path = Path(config.model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file does not exist: {model_path}")
    if model_path.suffix.lower() not in SUPPORTED_MODEL_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_MODEL_EXTENSIONS))
        raise ValueError(f"Stage-1 model baking supports {supported} assets")
    if config.view_set not in available_view_sets():
        known = ", ".join(available_view_sets())
        raise ValueError(f"Unknown view set '{config.view_set}'. Known view sets: {known}")
    if config.fps <= 0:
        raise ValueError("fps must be greater than zero")
    if config.frame_size <= 0:
        raise ValueError("frame_size must be greater than zero")
    if config.zoom <= 0:
        raise ValueError("zoom must be greater than zero")
    if config.style not in SUPPORTED_STYLES:
        known = ", ".join(sorted(SUPPORTED_STYLES))
        raise ValueError(f"Unknown style '{config.style}'. Known styles: {known}")
    if config.pixel_size <= 0:
        raise ValueError("pixel_size must be greater than zero")
    if config.max_frames is not None and config.max_frames <= 0:
        raise ValueError("max_frames must be greater than zero")


def _resolve_output_dir(project_dir: Path, slug: str, output_subdir: str | Path | None) -> Path:
    if output_subdir is None:
        output_dir = project_dir / "sprites" / slug
    else:
        subdir = Path(output_subdir)
        if subdir.is_absolute():
            raise ValueError("output_subdir must be relative to the project directory")
        output_dir = project_dir / subdir

    project_resolved = project_dir.resolve()
    output_resolved = output_dir.resolve()
    try:
        output_resolved.relative_to(project_resolved)
    except ValueError as exc:
        raise ValueError("output_subdir must stay inside the project directory") from exc
    return output_resolved


def _copy_source_model(model_path: Path, bake_output_dir: Path) -> Path:
    source_dir = bake_output_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    destination = source_dir / model_path.name
    if destination.resolve() != model_path.resolve():
        shutil.copy2(model_path, destination)
    return destination


def _directory_has_entries(path: Path) -> bool:
    return any(path.iterdir())


def _build_result(
    *,
    project_dir: Path,
    sprite_path: Path,
    bake_output_dir: Path,
    source_model_path: Path | None,
    renderer_result,
    write_result: SpriteWriteResult,
) -> ModelBakeResult:
    return ModelBakeResult(
        project_dir=project_dir,
        sprite_path=sprite_path,
        bake_output_dir=bake_output_dir,
        manifest_path=Path(renderer_result.manifest_path),
        source_model_path=source_model_path,
        sheet_paths=tuple(Path(path) for path in renderer_result.sheet_paths),
        godot_sprite_frames_path=(
            Path(renderer_result.godot_sprite_frames_path)
            if renderer_result.godot_sprite_frames_path
            else None
        ),
        godot_scene_path=(
            Path(renderer_result.godot_scene_path) if renderer_result.godot_scene_path else None
        ),
        frame_count=write_result.frame_count,
        animation_names=write_result.animation_names,
    )


def _safe_asset_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in value)
    return safe.strip("_") or "sprite"


def _optional_dependency_message() -> str:
    return (
        "The 3D model baker requires the Sprite Sage renderer dependencies. "
        "Install or refresh the project dependencies before baking GLB assets."
    )

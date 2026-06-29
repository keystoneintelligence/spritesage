from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import uuid
from typing import Iterable

from PIL import Image

from .sprite_file import Animation, SpriteFile

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
}


@dataclass(frozen=True)
class ArtImportResult:
    project_dir: Path
    sprite_path: Path
    asset_dir: Path
    base_image_path: Path
    frame_count: int
    animation_names: tuple[str, ...]


def natural_sort_key(value: str | Path) -> list[object]:
    text = Path(value).name if isinstance(value, Path) else str(value)
    parts = re.split(r"(\d+)", text.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def natural_sorted_paths(paths: Iterable[str | Path]) -> list[Path]:
    return sorted((Path(path) for path in paths), key=natural_sort_key)


def import_image_sequence(
    *,
    project_dir: str | Path,
    sprite_name: str,
    animation_name: str,
    image_paths: Iterable[str | Path],
) -> ArtImportResult:
    paths = natural_sorted_paths(image_paths)
    if not paths:
        raise ValueError("Select at least one image file.")
    _validate_image_files(paths)

    import_paths = _unique_import_paths(project_dir, sprite_name)
    animation = _safe_asset_name(animation_name, fallback="idle")
    frame_dir = import_paths.asset_dir / "animations" / animation
    frame_paths = _write_imported_frames(paths, frame_dir)

    return _write_sprite(
        project_dir=import_paths.project_dir,
        sprite_path=import_paths.sprite_path,
        asset_dir=import_paths.asset_dir,
        sprite_name=sprite_name,
        animations={animation: frame_paths},
    )


def import_folder(
    *,
    project_dir: str | Path,
    sprite_name: str,
    folder_path: str | Path,
    default_animation_name: str = "idle",
) -> ArtImportResult:
    folder = Path(folder_path)
    if not folder.is_dir():
        raise ValueError("Select an existing folder.")

    animation_sources: dict[str, list[Path]] = {}
    direct_images = _image_files_in_directory(folder)
    if direct_images:
        animation_sources[_safe_asset_name(default_animation_name, fallback="idle")] = direct_images

    for child in natural_sorted_paths(path for path in folder.iterdir() if path.is_dir()):
        child_images = _image_files_in_directory(child)
        if child_images:
            animation_sources[_safe_asset_name(child.name, fallback="animation")] = child_images

    if not animation_sources:
        raise ValueError("The selected folder does not contain any supported image files.")

    import_paths = _unique_import_paths(project_dir, sprite_name)
    animations: dict[str, list[Path]] = {}
    for requested_name, paths in animation_sources.items():
        animation_name = _unique_animation_name(requested_name, animations)
        frame_dir = import_paths.asset_dir / "animations" / animation_name
        animations[animation_name] = _write_imported_frames(paths, frame_dir)

    return _write_sprite(
        project_dir=import_paths.project_dir,
        sprite_path=import_paths.sprite_path,
        asset_dir=import_paths.asset_dir,
        sprite_name=sprite_name,
        animations=animations,
    )


def import_sprite_sheet(
    *,
    project_dir: str | Path,
    sprite_name: str,
    sheet_path: str | Path,
    frame_width: int,
    frame_height: int,
    animation_name: str,
    margin: int = 0,
    spacing: int = 0,
    ignore_empty: bool = True,
) -> ArtImportResult:
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("Frame width and height must be greater than zero.")
    if margin < 0 or spacing < 0:
        raise ValueError("Margin and spacing cannot be negative.")

    sheet = Path(sheet_path)
    if not sheet.is_file():
        raise ValueError("Select an existing sprite sheet image.")

    import_paths = _unique_import_paths(project_dir, sprite_name)
    animation = _safe_asset_name(animation_name, fallback="idle")
    frame_dir = import_paths.asset_dir / "animations" / animation
    frame_paths = _slice_fixed_grid_sheet(
        sheet_path=sheet,
        output_dir=frame_dir,
        frame_width=frame_width,
        frame_height=frame_height,
        margin=margin,
        spacing=spacing,
        ignore_empty=ignore_empty,
    )
    if not frame_paths:
        raise ValueError("No non-empty frames were found in the sprite sheet.")

    return _write_sprite(
        project_dir=import_paths.project_dir,
        sprite_path=import_paths.sprite_path,
        asset_dir=import_paths.asset_dir,
        sprite_name=sprite_name,
        animations={animation: frame_paths},
    )


def import_aseprite_json(
    *,
    project_dir: str | Path,
    sprite_name: str,
    json_path: str | Path,
    sheet_path: str | Path | None = None,
) -> ArtImportResult:
    aseprite_json = Path(json_path)
    if not aseprite_json.is_file():
        raise ValueError("Select an existing Aseprite JSON file.")

    data = json.loads(aseprite_json.read_text(encoding="utf-8"))
    sheet = _resolve_aseprite_sheet_path(data, aseprite_json, sheet_path)
    indexed_frames = _aseprite_indexed_frames(data)
    if not indexed_frames:
        raise ValueError("The Aseprite JSON file does not contain any frames.")

    tags = data.get("meta", {}).get("frameTags") or []
    animation_ranges: list[tuple[str, list[int]]] = []
    if tags:
        for index, tag in enumerate(tags):
            name = _safe_asset_name(str(tag.get("name") or f"animation_{index:02d}"))
            start = int(tag.get("from", 0))
            end = int(tag.get("to", start))
            direction = str(tag.get("direction") or "forward").lower()
            frame_indexes = list(range(start, end + 1))
            if direction == "reverse":
                frame_indexes.reverse()
            elif direction == "pingpong" and len(frame_indexes) > 1:
                frame_indexes = frame_indexes + frame_indexes[-2:0:-1]
            animation_ranges.append((name, frame_indexes))
    else:
        animation_ranges.append(("idle", list(range(len(indexed_frames)))))

    import_paths = _unique_import_paths(project_dir, sprite_name)
    animations: dict[str, list[Path]] = {}
    with Image.open(sheet) as sheet_image:
        sheet_rgba = sheet_image.convert("RGBA")
        for requested_name, frame_indexes in animation_ranges:
            animation_name = _unique_animation_name(requested_name, animations)
            frame_dir = import_paths.asset_dir / "animations" / animation_name
            frame_dir.mkdir(parents=True, exist_ok=True)
            frames: list[Path] = []
            for output_index, frame_index in enumerate(frame_indexes):
                try:
                    frame_data = indexed_frames[frame_index]
                except IndexError as exc:
                    raise ValueError(
                        f"Aseprite tag '{requested_name}' references missing frame {frame_index}."
                    ) from exc
                rect = frame_data.get("frame") or {}
                x = int(rect.get("x", 0))
                y = int(rect.get("y", 0))
                width = int(rect.get("w", 0))
                height = int(rect.get("h", 0))
                if width <= 0 or height <= 0:
                    raise ValueError("Aseprite frame rectangles must have positive size.")
                output_path = frame_dir / f"frame_{output_index:03d}.png"
                sheet_rgba.crop((x, y, x + width, y + height)).save(output_path)
                frames.append(output_path)
            if frames:
                animations[animation_name] = frames

    if not animations:
        raise ValueError("The Aseprite JSON file did not produce any animation frames.")

    return _write_sprite(
        project_dir=import_paths.project_dir,
        sprite_path=import_paths.sprite_path,
        asset_dir=import_paths.asset_dir,
        sprite_name=sprite_name,
        animations=animations,
    )


@dataclass(frozen=True)
class _ImportPaths:
    project_dir: Path
    sprite_path: Path
    asset_dir: Path


def _unique_import_paths(project_dir: str | Path, sprite_name: str) -> _ImportPaths:
    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise ValueError("Project directory is not valid.")

    slug = _safe_asset_name(sprite_name, fallback="sprite")
    suffix = 1
    while True:
        candidate = slug if suffix == 1 else f"{slug}_{suffix}"
        sprite_path = project / f"{candidate}.sprite"
        asset_dir = project / "sprites" / candidate
        if not sprite_path.exists() and not asset_dir.exists():
            return _ImportPaths(project_dir=project, sprite_path=sprite_path, asset_dir=asset_dir)
        suffix += 1


def _write_sprite(
    *,
    project_dir: Path,
    sprite_path: Path,
    asset_dir: Path,
    sprite_name: str,
    animations: dict[str, list[Path]],
) -> ArtImportResult:
    if not animations:
        raise ValueError("At least one animation is required.")

    first_frames = next(iter(animations.values()))
    if not first_frames:
        raise ValueError("At least one frame is required.")
    base_image = first_frames[0]
    width, height = _image_size(base_image)

    sprite = SpriteFile(
        uuid=str(uuid.uuid4()),
        name=sprite_name.strip() or sprite_path.stem,
        description="Imported existing art.",
        width=width,
        height=height,
        base_image=str(base_image),
        animations={
            name: Animation(name=name, frames=[str(frame) for frame in frames])
            for name, frames in animations.items()
        },
        include_base_image_in_animations=False,
    )
    sprite_path.parent.mkdir(parents=True, exist_ok=True)
    sprite.save(str(sprite_path), str(project_dir))
    return ArtImportResult(
        project_dir=project_dir,
        sprite_path=sprite_path,
        asset_dir=asset_dir,
        base_image_path=base_image,
        frame_count=sum(len(frames) for frames in animations.values()),
        animation_names=tuple(animations.keys()),
    )


def _write_imported_frames(image_paths: list[Path], output_dir: Path) -> list[Path]:
    _validate_image_files(image_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    for index, image_path in enumerate(image_paths):
        output_path = output_dir / f"frame_{index:03d}.png"
        with Image.open(image_path) as image:
            image.convert("RGBA").save(output_path)
        output_paths.append(output_path)
    return output_paths


def _slice_fixed_grid_sheet(
    *,
    sheet_path: Path,
    output_dir: Path,
    frame_width: int,
    frame_height: int,
    margin: int,
    spacing: int,
    ignore_empty: bool,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    with Image.open(sheet_path) as sheet_image:
        sheet = sheet_image.convert("RGBA")
        output_index = 0
        y = margin
        while y + frame_height <= sheet.height:
            x = margin
            while x + frame_width <= sheet.width:
                frame = sheet.crop((x, y, x + frame_width, y + frame_height))
                if not ignore_empty or not _is_fully_transparent(frame):
                    output_path = output_dir / f"frame_{output_index:03d}.png"
                    frame.save(output_path)
                    output_paths.append(output_path)
                    output_index += 1
                x += frame_width + spacing
            y += frame_height + spacing
    return output_paths


def _image_files_in_directory(directory: Path) -> list[Path]:
    return natural_sorted_paths(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


def _validate_image_files(paths: list[Path]) -> None:
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Image file does not exist: {path}")
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))
            raise ValueError(f"Unsupported image type for {path.name}. Supported: {supported}")


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _is_fully_transparent(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    return alpha.getbbox() is None


def _safe_asset_name(value: str, *, fallback: str = "sprite") -> str:
    safe = "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in value)
    return safe.strip("_") or fallback


def _unique_animation_name(name: str, existing: dict[str, list[Path]]) -> str:
    if name not in existing:
        return name
    suffix = 2
    while f"{name}_{suffix}" in existing:
        suffix += 1
    return f"{name}_{suffix}"


def _resolve_aseprite_sheet_path(
    data: dict,
    json_path: Path,
    explicit_sheet_path: str | Path | None,
) -> Path:
    if explicit_sheet_path:
        sheet_path = Path(explicit_sheet_path)
    else:
        image_value = data.get("meta", {}).get("image")
        if not image_value:
            raise ValueError("Select the sheet image for this Aseprite JSON file.")
        sheet_path = Path(str(image_value))
        if not sheet_path.is_absolute():
            sheet_path = json_path.parent / sheet_path
    if not sheet_path.is_file():
        raise ValueError(f"Aseprite sheet image does not exist: {sheet_path}")
    return sheet_path


def _aseprite_indexed_frames(data: dict) -> list[dict]:
    frames = data.get("frames")
    if isinstance(frames, dict):
        return [frame for _, frame in frames.items() if isinstance(frame, dict)]
    if isinstance(frames, list):
        return [frame for frame in frames if isinstance(frame, dict)]
    return []

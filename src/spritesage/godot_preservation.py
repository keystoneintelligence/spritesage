"""Plan minimal updates relative to the last successful Godot export.

The first slice supports fixed frame layouts. Structural edits fail closed rather
than guessing which game events or collision shapes belong to a moved frame.
"""

import hashlib
import io
import json
import math
import re
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from . import godot_text as text
from .godot_export_transaction import ExportPlan, recover_pending_export

if TYPE_CHECKING:
    from .exporter import GodotSpriteExporter

MANIFEST = ".spritesage-export.json"


def _pixels(image: Image.Image) -> str:
    rgba = image.convert("RGBA")
    return hashlib.sha256(str(rgba.size).encode() + rgba.tobytes()).hexdigest()


def _image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _source(exporter: "GodotSpriteExporter", plan: ExportPlan) -> dict:
    sprite = exporter.sprite_file
    result = {
        "uuid": sprite.uuid,
        "asset_name": exporter.asset_name,
        "size": [sprite.width, sprite.height],
        "pixel_art": sprite.pixel_art,
        "animations": {},
    }
    for name in sorted(sprite.animations):
        animation = sprite.get_animation_playback(name)
        frames = []
        for path, hold in zip(animation.frames, animation.frame_durations, strict=True):
            frame_path = Path(path)
            plan.guards[frame_path] = frame_path.read_bytes()
            frames.append(
                {
                    "path": str(frame_path.resolve()),
                    "hash": _pixels(_image(frame_path)),
                    "hold": hold,
                }
            )
        result["animations"][name] = {
            "fps": animation.fps,
            "loop": animation.loop,
            "frames": frames,
        }
    if not exporter.frame_count:
        if not sprite.base_image:
            raise ValueError("Cannot export a static sprite without a base image.")
        path = Path(sprite.base_image)
        plan.guards[path] = path.read_bytes()
        result["base"] = {"path": str(path.resolve()), "hash": _pixels(_image(path))}
    return result


def _read(plan: ExportPlan, path: Path) -> bytes:
    content = path.read_bytes()
    plan.guards[path] = content
    return content


def _frames(source: str, animation: dict) -> list[dict]:
    span = animation["frames"]
    if source[span.start] != "[":
        raise ValueError("Unsupported Godot frames array.")
    return [text.fields(source, item) for item in text.items(source, span)]


def _region(resource: str, frame: dict, sheet_path: Path) -> tuple[int, int, int, int]:
    texture = re.fullmatch(r'SubResource\("([^"\\]+)"\)', frame["texture"].text(resource))
    if not texture:
        raise ValueError("Godot frame texture was replaced. Export to a new folder instead.")
    sections = re.findall(
        r'(?ms)^\[sub_resource type="AtlasTexture" id="'
        + re.escape(texture[1])
        + r'"\]\s*\n(.*?)(?=^\[|\Z)',
        resource,
    )
    if len(sections) != 1:
        raise ValueError("Godot frame atlas cannot be mapped safely.")
    atlas = re.search(r'(?m)^atlas\s*=\s*ExtResource\("([^"\\]+)"\)\s*$', sections[0])
    region = re.search(r"(?m)^region\s*=\s*Rect2\(([^)]+)\)\s*$", sections[0])
    if not atlas or not region:
        raise ValueError("Godot atlas layout changed. Export to a new folder instead.")
    externals = re.findall(r"(?m)^\[ext_resource\s+([^\n]+)\]\s*$", resource)
    matching = [
        header for header in externals if re.search(r'\bid="' + re.escape(atlas[1]) + r'"', header)
    ]
    if len(matching) != 1:
        raise ValueError("Godot atlas reference changed.")
    path = re.search(r'\bpath="((?:[^"\\]|\\.)*)"', matching[0])
    # Godot resaves relative paths as res:// paths. Verify the actual resolved
    # destination below as well, not just the basename.
    if not path or Path(json.loads('"' + path[1] + '"')).name != sheet_path.name:
        raise ValueError("Godot atlas texture changed. Export to a new folder instead.")
    texture_path = json.loads('"' + path[1] + '"')
    if texture_path.startswith("res://"):
        project_root = next(
            (
                parent
                for parent in sheet_path.absolute().parents
                if (parent / "project.godot").exists()
            ),
            None,
        )
        if project_root is None:
            raise ValueError("Cannot resolve Godot project texture path safely.")
        resolved = project_root / texture_path.removeprefix("res://")
    else:
        resolved = sheet_path.parent / texture_path
    if resolved.resolve() != sheet_path.resolve():
        raise ValueError("Godot atlas points to a different texture. Export to a new folder.")
    values = [float(value.strip()) for value in region[1].split(",")]
    if len(values) != 4 or any(not value.is_integer() for value in values):
        raise ValueError("Unsupported Godot atlas rectangle.")
    return (int(values[0]), int(values[1]), int(values[2]), int(values[3]))


def _playback(resource: str) -> dict:
    result = {}
    for name, animation in text.animations(resource).items():
        result[name] = {
            "fps": text.scalar(resource, animation["speed"], allow_zero=True),
            "loop": text.scalar(resource, animation["loop"]),
            "holds": [
                text.scalar(resource, frame["duration"]) for frame in _frames(resource, animation)
            ],
        }
    return result


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _new(exporter: "GodotSpriteExporter", plan: ExportPlan, source: dict) -> ExportPlan:
    root = exporter.output_dir
    # No baseline means no overwrite authority, including exports from older
    # versions. Unrelated files are allowed; same-name collisions are not.
    names = [
        f"{exporter.asset_name}.tscn",
        f"{exporter.asset_name}_frames.tres",
        f"{exporter.asset_name}_sheet.png",
        f"{exporter.asset_name}.png",
    ]
    for name in names:
        path = root / name
        plan.guards[path] = path.read_bytes() if path.exists() else None
        if path.exists():
            raise ValueError(
                "Existing Godot files have no SpriteSage export record. Choose a new export folder to preserve them."
            )
    # Render outside the destination. No partial files appear on cancel/failure.
    with tempfile.TemporaryDirectory(prefix="spritesage-godot-") as directory:
        staged = type(exporter)(exporter.sprite_file, directory, exporter.progress_callback)
        staged._write_new_export()
        for path in Path(directory).iterdir():
            if path.is_file():
                plan.writes[root / path.name] = path.read_bytes()
    manifest = {"version": 1, "source": source, "slots": {}, "delivered": {}}
    if exporter.frame_count:
        resource = plan.writes[root / f"{exporter.asset_name}_frames.tres"].decode("utf-8")
        sheet_name = f"{exporter.asset_name}_sheet.png"
        sheet = Image.open(io.BytesIO(plan.writes[root / sheet_name])).convert("RGBA")
        manifest["delivered"] = _playback(resource)
        for name, animation in text.animations(resource).items():
            slots = []
            for frame in _frames(resource, animation):
                region = _region(resource, frame, root / sheet_name)
                x, y, w, h = region
                slots.append(
                    {
                        "id": uuid.uuid4().hex,
                        "region": list(region),
                        "hash": _pixels(sheet.crop((x, y, x + w, y + h))),
                    }
                )
            manifest["slots"][name] = slots
    else:
        image = Image.open(io.BytesIO(plan.writes[root / f"{exporter.asset_name}.png"]))
        manifest["base_hash"] = _pixels(image)
    plan.writes[root / MANIFEST] = _manifest_bytes(manifest)
    plan.creations.append(f"{exporter.asset_name}: create Godot asset")
    return plan


def _same_layout(old: dict, new: dict) -> None:
    for key in ("uuid", "asset_name", "size", "pixel_art"):
        if old[key] != new[key]:
            raise ValueError(
                "Sprite identity, canvas, or texture filtering changed. Choose a new export folder; existing game setup will be preserved."
            )
    if old["animations"].keys() != new["animations"].keys():
        raise ValueError(
            "Animations were added, removed, or renamed. Choose a new export folder until structural updates are supported."
        )
    for name, animation in new["animations"].items():
        previous = old["animations"][name]["frames"]
        frames = animation["frames"]
        if len(previous) != len(frames):
            raise ValueError(
                f"{name}: frame count changed. Choose a new export folder to preserve frame-bound gameplay data."
            )
        for index, frame in enumerate(frames):
            if frame["path"] != previous[index]["path"] and any(
                frame["path"] == other["path"] for other in previous
            ):
                raise ValueError(
                    f"{name}: frame order changed. Choose a new export folder to preserve frame-bound gameplay data."
                )
            if frame["hash"] != previous[index]["hash"] and any(
                frame["hash"] == other["hash"]
                for position, other in enumerate(previous)
                if position != index
            ):
                raise ValueError(
                    f"{name}: ambiguous frame replacement or reorder. Choose a new export folder."
                )


def _equivalent(first: float | bool, second: float | bool) -> bool:
    if isinstance(first, bool) or isinstance(second, bool):
        return type(first) is type(second) and first == second
    # Godot stores frame durations at float precision. Resaving a resource must
    # not turn engine rounding into a supposed authored conflict.
    return math.isclose(first, second, rel_tol=1e-6, abs_tol=1e-9)


def _setting(
    plan: ExportPlan,
    label: str,
    old: float | bool,
    new: float | bool,
    current: float | bool,
    delivered: float | bool,
    span: text.Span,
    edits: list,
    *,
    source_changed: bool | None = None,
    description: str | None = None,
) -> None:
    if (new == old if source_changed is None else not source_changed) or _equivalent(new, current):
        return
    update = description or f"{label}: {current} → {new}"
    plan.updates.append(update)
    if not _equivalent(current, delivered):
        plan.conflicts.append(update)
    value = str(new).lower() if isinstance(new, bool) else f"{new:.12g}"
    edits.append((span, value))


def _update(
    exporter: "GodotSpriteExporter", plan: ExportPlan, source: dict, manifest: dict
) -> ExportPlan:
    root = exporter.output_dir
    old = manifest["source"]
    _same_layout(old, source)
    scene_path = root / f"{exporter.asset_name}.tscn"
    _read(plan, scene_path)  # User-owned scene: verify it exists, never rewrite it.
    if not exporter.frame_count:
        image_path = root / f"{exporter.asset_name}.png"
        destination = _image(image_path)
        _read(plan, image_path)
        if source["base"]["hash"] != old["base"]["hash"]:
            replacement = _image(Path(source["base"]["path"]))
            if replacement.size != destination.size:
                raise ValueError("Sprite image canvas changed. Choose a new export folder.")
            plan.updates.append(f"{exporter.asset_name}: replace sprite image")
            if _pixels(destination) != manifest["base_hash"]:
                plan.conflicts.append(plan.updates[-1])
            plan.writes[image_path] = _png(replacement)
            manifest["base_hash"] = _pixels(replacement)
    else:
        resource_path = root / f"{exporter.asset_name}_frames.tres"
        resource = _read(plan, resource_path).decode("utf-8")
        animations = text.animations(resource)
        sheet_path = root / f"{exporter.asset_name}_sheet.png"
        _read(plan, sheet_path)
        sheet = _image(sheet_path)
        edits = []
        image_changed = False
        for name, animation in source["animations"].items():
            if name not in animations:
                raise ValueError(
                    f"Godot animation '{name}' was removed or renamed. Choose a new export folder."
                )
            previous = old["animations"][name]
            target = animations[name]
            frames = _frames(resource, target)
            slots = manifest["slots"][name]
            if len(frames) != len(slots):
                raise ValueError(f"{name}: Godot frame count changed. Export to a new folder.")
            delivered = manifest["delivered"][name]
            current_fps = float(text.scalar(resource, target["speed"], allow_zero=True))
            effective_fps = animation["fps"] if animation["fps"] != previous["fps"] else current_fps
            for property_name, target_name in (("fps", "speed"), ("loop", "loop")):
                span = target[target_name]
                _setting(
                    plan,
                    f"{name}: {property_name}",
                    previous[property_name],
                    animation[property_name],
                    text.scalar(resource, span, allow_zero=property_name == "fps"),
                    delivered[property_name],
                    span,
                    edits,
                )
            for index, (frame, slot, incoming, before) in enumerate(
                zip(frames, slots, animation["frames"], previous["frames"], strict=True)
            ):
                region = _region(resource, frame, sheet_path)
                if list(region) != slot["region"]:
                    raise ValueError(f"{name}: Godot frame layout changed. Export to a new folder.")
                x, y, w, h = region
                if x < 0 or y < 0 or x + w > sheet.width or y + h > sheet.height:
                    raise ValueError("Godot sprite sheet dimensions changed.")
                span = frame["duration"]
                if incoming["hold"] != before["hold"]:
                    if effective_fps == 0 or current_fps == 0:
                        raise ValueError(
                            f"{name}: frame duration cannot be updated while Godot FPS is zero. Set a positive FPS before exporting duration changes."
                        )
                    # The editor exposes milliseconds. Preserve that intent even
                    # when Godot owns a different FPS; patch only this hold.
                    desired_seconds = incoming["hold"] / animation["fps"]
                    current_hold = float(text.scalar(resource, span))
                    _setting(
                        plan,
                        f"{name}: frame {index + 1} duration",
                        before["hold"],
                        desired_seconds * effective_fps,
                        current_hold,
                        delivered["holds"][index],
                        span,
                        edits,
                        source_changed=True,
                        description=f"{name}: frame {index + 1} duration: {current_hold / current_fps * 1000:.12g} ms \u2192 {desired_seconds * 1000:.12g} ms",
                    )
                if incoming["hash"] != before["hash"]:
                    replacement = _image(Path(incoming["path"]))
                    if replacement.size != (w, h):
                        raise ValueError(
                            f"{name}: replacement frame {index + 1} must match the {w}×{h} canvas. Resize it explicitly before export."
                        )
                    current_hash = _pixels(sheet.crop((x, y, x + w, y + h)))
                    if _pixels(replacement) != current_hash:
                        plan.updates.append(f"{name}: replace frame {index + 1} image")
                        if current_hash != slot["hash"]:
                            plan.conflicts.append(plan.updates[-1])
                        sheet.paste(replacement, (x, y))
                        image_changed = True
                    slot["hash"] = _pixels(replacement)
        if edits:
            resource = text.patch(resource, edits)
            plan.writes[resource_path] = resource.encode("utf-8")
        if image_changed:
            plan.writes[sheet_path] = _png(sheet)
        manifest["delivered"] = _playback(resource)
    # A source change already applied independently in Godot is acknowledged
    # without overwriting it or showing a spurious update confirmation.
    if source != old:
        manifest["source"] = source
        plan.writes[root / MANIFEST] = _manifest_bytes(manifest)
    return plan


def prepare_export(exporter: "GodotSpriteExporter") -> ExportPlan:
    root = exporter.output_dir
    recover_pending_export(root)
    plan = ExportPlan(root=root, exported_dirs=[root])
    source = _source(exporter, plan)
    manifest_path = root / MANIFEST
    plan.guards[manifest_path] = manifest_path.read_bytes() if manifest_path.exists() else None
    if not manifest_path.exists():
        return _new(exporter, plan, source)
    try:
        manifest = json.loads(_read(plan, manifest_path))
        if manifest.get("version") != 1:
            raise ValueError("Unsupported Godot export record version.")
        return _update(exporter, plan, source, manifest)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(
            "Godot export record or resource cannot be mapped safely. Choose a new export folder."
        ) from error

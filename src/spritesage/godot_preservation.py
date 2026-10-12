"""Plan minimal updates relative to the last successful Godot export.

Frame sequence edits are reviewable updates. Retain surviving atlas cells and
authored frame properties; disclose frame-index gameplay references for review.
"""

import copy
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
from .godot_export_transaction import ExportPlan, stage_pending_recovery
from .godot_export_diff import review_candidates

if TYPE_CHECKING:
    from .exporter import GodotSpriteExporter

MANIFEST = ".spritesage-export.json"


def _pixels(image: Image.Image) -> str:
    rgba = image.convert("RGBA")
    return hashlib.sha256(str(rgba.size).encode() + rgba.tobytes()).hexdigest()


def _image(path: Path, plan: ExportPlan | None = None) -> Image.Image:
    with Image.open(io.BytesIO(_read(plan, path)) if plan else path) as image:
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
    if not exporter.frame_count and sprite.base_image:
        path = Path(sprite.base_image)
        plan.guards[path] = path.read_bytes()
        result["base"] = {"path": str(path.resolve()), "hash": _pixels(_image(path))}
    return result


def _read(plan: ExportPlan, path: Path) -> bytes:
    content = path.read_bytes() if path.exists() else None
    plan.guards[path] = content
    candidate = plan.inputs.get(path, content)
    if candidate is None:
        raise FileNotFoundError(path)
    return candidate


def _exists(plan: ExportPlan, path: Path) -> bool:
    return plan.inputs[path] is not None if path in plan.inputs else path.exists()


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
    if _resolve_reference(texture_path, sheet_path) != sheet_path.resolve():
        raise ValueError("Godot atlas points to a different texture. Export to a new folder.")
    values = [float(value.strip()) for value in region[1].split(",")]
    if len(values) != 4 or any(not value.is_integer() for value in values):
        raise ValueError("Unsupported Godot atlas rectangle.")
    return (int(values[0]), int(values[1]), int(values[2]), int(values[3]))


def _resolve_reference(reference: str, target: Path) -> Path:
    if reference.startswith("res://"):
        project_root = next(
            (parent for parent in target.absolute().parents if (parent / "project.godot").exists()),
            None,
        )
        if project_root is None:
            raise ValueError("Cannot resolve Godot project resource path safely.")
        return (project_root / reference.removeprefix("res://")).resolve()
    return (target.parent / reference).resolve()


def _check_scene_binding(scene: str, target: Path, property_name: str) -> None:
    """Do not report a successful update to a resource the scene no longer uses."""
    for header in re.findall(r"(?m)^\[ext_resource\s+([^\n]+)\]\s*$", scene):
        path = re.search(r'\bpath="((?:[^"\\]|\\.)*)"', header)
        resource_id = re.search(r'\bid="([^"\\]+)"', header)
        if path is None or resource_id is None:
            continue
        reference = json.loads('"' + path[1] + '"')
        if Path(reference).name != target.name:
            continue
        if _resolve_reference(reference, target) == target.resolve() and re.search(
            r"(?m)^"
            + property_name
            + r'\s*=\s*ExtResource\("'
            + re.escape(resource_id[1])
            + r'"\)\s*$',
            scene,
        ):
            return
    raise ValueError(
        "Godot scene no longer uses the exported resource. Choose a new export folder to preserve the new binding."
    )


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
                        "texture": frame["texture"].text(resource),
                    }
                )
            manifest["slots"][name] = slots
    else:
        manifest["base_file"] = Path(exporter.sprite_file.base_image).name
        image = Image.open(io.BytesIO(plan.writes[root / manifest["base_file"]]))
        manifest["base_hash"] = _pixels(image)
    plan.writes[root / MANIFEST] = _manifest_bytes(manifest)
    plan.creations.append(f"{exporter.asset_name}: create Godot asset")
    return plan


def _frame_mapping(previous: list[dict], incoming: list[dict]) -> list[int | None]:
    """Match unchanged identities before treating unmatched same-position art as replacements."""
    result: list[int | None] = [None] * len(incoming)
    available = set(range(len(previous)))
    for field in ("path", "hash"):
        for index, frame in enumerate(incoming):
            if result[index] is not None:
                continue
            matches = [old for old in sorted(available) if previous[old][field] == frame[field]]
            if matches:
                old = next(
                    (old for old in matches if previous[old]["hold"] == frame["hold"]), matches[0]
                )
                result[index] = old
                available.remove(old)
    for index, frame in enumerate(incoming):
        if result[index] is None:
            # A repeated source frame can reuse its atlas cell without inference.
            duplicate = next(
                (
                    old
                    for old, before in enumerate(previous)
                    if before["path"] == frame["path"] and before["hash"] == frame["hash"]
                ),
                None,
            )
            if duplicate is not None:
                result[index] = duplicate
            elif len(previous) == len(incoming) and index in available:
                result[index] = index
                available.remove(index)
    return result


def _frame_array(resource: str, span: text.Span, records: list[str], edits: list) -> None:
    # Preserve all fields of each surviving dictionary, including unknown game metadata.
    edits[:] = [
        (target, value) for target, value in edits if not (span.start <= target.start < span.end)
    ]
    edits.append((span, "[\n" + ",\n".join(records) + "\n]"))


def _texture_id(resource: str, sheet_path: Path) -> str:
    for header in re.findall(r"(?m)^\[ext_resource\s+([^\n]+)\]\s*$", resource):
        path = re.search(r'\bpath="((?:[^"\\]|\\.)*)"', header)
        identifier = re.search(r'\bid="([^"\\]+)"', header)
        if path and identifier:
            reference = json.loads('"' + path[1] + '"')
            if (
                Path(reference).name == sheet_path.name
                and _resolve_reference(reference, sheet_path) == sheet_path.resolve()
            ):
                return identifier[1]
    raise ValueError("Godot sprite sheet resource reference is missing.")


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


def _minimal_update(
    exporter: "GodotSpriteExporter", plan: ExportPlan, source: dict, manifest: dict
) -> ExportPlan:
    root = exporter.output_dir
    old = manifest["source"]
    physical_name = manifest.get("asset_file_name", exporter.asset_name)
    scene_path = root / f"{physical_name}.tscn"
    scene = _read(plan, scene_path).decode("utf-8")  # User-owned: never rewrite it.
    if "base_hash" in manifest:
        base_file = manifest.get("base_file", f"{exporter.asset_name}.png")
        image_path = root / base_file
        image_path.resolve().relative_to(root.resolve())
        _check_scene_binding(scene, image_path, "texture")
        destination = _image(image_path, plan)
        _read(plan, image_path)
        if source["base"]["hash"] != old["base"]["hash"]:
            replacement = exporter.render_base_image()
            if _pixels(replacement) != _pixels(destination):
                plan.updates.append(f"{exporter.asset_name}: replace sprite image")
                if _pixels(destination) != manifest["base_hash"]:
                    plan.conflicts.append(plan.updates[-1])
                plan.writes[image_path] = _png(replacement)
            manifest["base_hash"] = _pixels(replacement)
    else:
        resource_path = root / manifest.get("resource_file", f"{physical_name}_frames.tres")
        _check_scene_binding(scene, resource_path, "sprite_frames")
        resource = _read(plan, resource_path).decode("utf-8")
        animations = text.animations(resource)
        sheet_path = root / f"{physical_name}_sheet.png"
        _read(plan, sheet_path)
        sheet = _image(sheet_path, plan)
        edits = []
        image_changed = False
        mappings = {
            name: _frame_mapping(old["animations"][name]["frames"], animation["frames"])
            for name, animation in source["animations"].items()
        }
        changed_paths = list(
            dict.fromkeys(
                incoming["path"]
                for name, animation in source["animations"].items()
                for incoming, before_index in zip(animation["frames"], mappings[name], strict=True)
                if before_index is None
                or incoming["hash"] != old["animations"][name]["frames"][before_index]["hash"]
            )
        )
        new_atlases = []
        append_row, append_index = sheet.height, 0
        replacements = (
            dict(
                zip(
                    changed_paths,
                    exporter.sheet_gen.render_frames(changed_paths, exporter.progress_callback)[0],
                    strict=True,
                )
            )
            if changed_paths
            else {}
        )
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
            mapping = mappings[name]
            structural = mapping != list(range(len(previous["frames"])))
            if structural:
                removed = sorted(set(range(len(previous["frames"]))) - set(mapping))
                plan.updates.append(
                    f"{name}: frame count: {len(previous['frames'])} → {len(mapping)}; update frame order/list"
                )
                order = [
                    str(position + 1) if position is not None else "new" for position in mapping
                ]
                preview = ", ".join(order[:24]) + (
                    f", … ({len(order)} frames)" if len(order) > 24 else ""
                )
                plan.updates.append(
                    f"{name}: frame list (previous positions): {preview or '(empty)'}"
                )
                if removed:
                    plan.updates.append(
                        f"{name}: remove frames: " + ", ".join(str(index + 1) for index in removed)
                    )
                    for removed_index in removed:
                        removed_frame = frames[removed_index]
                        x, y, w, h = _region(resource, removed_frame, sheet_path)
                        if (
                            not _equivalent(
                                float(text.scalar(resource, removed_frame["duration"])),
                                delivered["holds"][removed_index],
                            )
                            or _pixels(sheet.crop((x, y, x + w, y + h)))
                            != slots[removed_index]["hash"]
                            or set(removed_frame) - {"duration", "texture"}
                        ):
                            plan.conflicts.append(
                                f"{name}: remove frame {removed_index + 1}, including its Godot edits"
                            )
                plan.notices.append(
                    f"{name}: frame-index metadata, scripts and event tracks remain as authored. Review their references after changing the frame list."
                )
            records, new_slots = [], []
            frame_spans = text.items(resource, target["frames"])
            for index, (incoming, before_index) in enumerate(
                zip(animation["frames"], mapping, strict=True)
            ):
                if before_index is None:
                    replacement = replacements[incoming["path"]]
                    w, h = source["size"]
                    cols = sheet.width // w
                    x, y = (append_index % cols) * w, append_row + (append_index // cols) * h
                    append_index += 1
                    if y + h > sheet.height:
                        expanded = Image.new(
                            "RGBA", (sheet.width, exporter.sheet_gen.next_power_of_two(y + h))
                        )
                        expanded.paste(sheet, (0, 0))
                        sheet = expanded
                    sheet.paste(replacement, (x, y))
                    image_changed = True
                    sub_id = "AtlasTexture_" + uuid.uuid4().hex[:12]
                    atlas_id = _texture_id(resource, sheet_path)
                    new_atlases.append(
                        f'[sub_resource type="AtlasTexture" id="{sub_id}"]\natlas = ExtResource("{atlas_id}")\nregion = Rect2({x}, {y}, {w}, {h})\n\n'
                    )
                    hold = (
                        incoming["hold"] * effective_fps / animation["fps"]
                        if effective_fps
                        else incoming["hold"]
                    )
                    records.append(
                        f'{{"duration": {hold:.12g}, "texture": SubResource("{sub_id}")}}'
                    )
                    new_slots.append(
                        {
                            "id": uuid.uuid4().hex,
                            "region": [x, y, w, h],
                            "hash": _pixels(replacement),
                        }
                    )
                    plan.updates.append(f"{name}: add frame {index + 1} image")
                    continue
                frame, slot, before = (
                    frames[before_index],
                    dict(slots[before_index]),
                    previous["frames"][before_index],
                )
                if before_index in mapping[:index]:
                    slot["id"] = uuid.uuid4().hex
                frame_edit_start = len(edits)
                region = _region(resource, frame, sheet_path)
                if list(region) != slot["region"]:
                    raise ValueError(f"{name}: Godot frame layout changed. Export to a new folder.")
                x, y, w, h = region
                if x < 0 or y < 0 or x + w > sheet.width or y + h > sheet.height:
                    raise ValueError("Godot sprite sheet dimensions changed.")
                span = frame["duration"]
                if incoming["hold"] != before["hold"]:
                    if effective_fps == 0:
                        raise ValueError(
                            f"{name}: frame duration cannot be updated while Godot FPS is zero. Set a positive FPS before exporting duration changes."
                        )
                    # The editor exposes milliseconds. Preserve that intent even
                    # when Godot owns a different FPS; patch only this hold.
                    desired_seconds = incoming["hold"] / animation["fps"]
                    current_hold = float(text.scalar(resource, span))
                    current_duration = (
                        f"{current_hold / current_fps * 1000:.12g} ms"
                        if current_fps
                        else "paused (0 FPS)"
                    )
                    _setting(
                        plan,
                        f"{name}: frame {index + 1} duration",
                        before["hold"],
                        desired_seconds * effective_fps,
                        current_hold,
                        delivered["holds"][before_index],
                        span,
                        edits,
                        source_changed=True,
                        description=f"{name}: frame {index + 1} duration: {current_duration} \u2192 {desired_seconds * 1000:.12g} ms",
                    )
                if incoming["hash"] != before["hash"]:
                    replacement = replacements[incoming["path"]]
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
                new_slots.append(slot)
                span = frame_spans[before_index]
                local_edits = [
                    (text.Span(edit.start - span.start, edit.end - span.start), value)
                    for edit, value in edits[frame_edit_start:]
                    if span.start <= edit.start < span.end
                ]
                records.append(text.patch(span.text(resource), local_edits))
            if structural:
                _frame_array(resource, target["frames"], records, edits)
            manifest["slots"][name] = new_slots
        if new_atlases:
            section = re.search(r"(?m)^\[resource\]", resource)
            if section is None:
                raise ValueError("Missing Godot resource section.")
            edits.append((text.Span(section.start(), section.start()), "".join(new_atlases)))
        if edits:
            resource = text.patch(resource, edits)
            if new_atlases:
                load_steps = 1 + len(
                    re.findall(r"(?m)^\[(?:ext_resource|sub_resource)\s", resource)
                )
                resource = re.sub(
                    r"(?m)^(\[gd_resource[^\n]*?\bload_steps=)\d+",
                    lambda match: match[1] + str(load_steps),
                    resource,
                    count=1,
                )
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


def _adopt(exporter, plan, source):
    """Bootstrap older exports by preserving their authored settings and fields."""
    from .godot_reconcile import reconcile

    root = exporter.output_dir
    scene_path = root / f"{exporter.asset_name}.tscn"
    if not _exists(plan, scene_path):
        # A new asset in a populated folder can still collide with textures/resources.
        return _new(exporter, plan, source)
    scene = _read(plan, scene_path).decode("utf-8")
    baseline = copy.deepcopy(source)
    manifest = {"version": 1, "source": baseline, "slots": {}, "delivered": {}}
    resource_path = root / f"{exporter.asset_name}_frames.tres"
    if exporter.frame_count or _exists(plan, resource_path):
        resource = _read(plan, resource_path).decode("utf-8")
        sheet_path = root / f"{exporter.asset_name}_sheet.png"
        sheet = _image(sheet_path, plan)
        _read(plan, sheet_path)
        manifest["delivered"] = _playback(resource)
        animations = text.animations(resource)
        for name, animation in baseline["animations"].items():
            slots = []
            for frame in _frames(resource, animations[name]) if name in animations else []:
                try:
                    region = _region(resource, frame, sheet_path)
                    x, y, w, h = region
                    image_hash = _pixels(sheet.crop((x, y, x + w, y + h)))
                except ValueError:
                    region, image_hash = [0, 0, 0, 0], ""
                slots.append(
                    {
                        "id": uuid.uuid4().hex,
                        "region": list(region),
                        "hash": image_hash,
                        "texture": frame["texture"].text(resource),
                    }
                )
            manifest["slots"][name] = slots
            for frame in animation["frames"]:
                frame["hash"] = ""  # Export art explicitly; retain all existing playback values.
    else:
        from .godot_reconcile import _root

        node = _root(scene)
        match = re.fullmatch(r'ExtResource\("([^"]+)"\)', node.properties["texture"].text(scene))
        if match is None:
            base_file = Path(exporter.sprite_file.base_image).name
        else:
            ext = next(
                s
                for s in text.sections(scene)
                if s.kind == "ext_resource" and s.attributes.get("id") == json.dumps(match[1])
            )
            base_file = Path(json.loads(ext.attributes["path"])).name
        manifest["base_file"] = base_file
        manifest["base_hash"] = _pixels(_image(root / base_file, plan))
        baseline["base"]["hash"] = ""
    plan.notices.append(
        "This export has no prior source baseline. Existing Godot playback, metadata and scene content are retained; artwork replacements are listed for review."
    )
    return reconcile(exporter, plan, source, manifest)


def _update(exporter, plan, source, manifest):
    from .godot_reconcile import reconcile

    old = manifest["source"]
    if source == old:
        return plan  # Godot-only edits, including structural edits, are not overwrite intent.
    structural = (
        any(old[key] != source[key] for key in ("uuid", "asset_name", "size", "pixel_art"))
        or old["animations"].keys() != source["animations"].keys()
    )
    if (
        structural
        or manifest.get("inline_frames")
        or any(name != target for name, target in manifest.get("animation_targets", {}).items())
    ):
        return reconcile(exporter, plan, source, manifest)
    if "base_hash" not in manifest:
        resource_path = exporter.output_dir / manifest.get(
            "resource_file", f"{manifest.get('asset_file_name', exporter.asset_name)}_frames.tres"
        )
        if _exists(plan, resource_path):
            resource = _read(plan, resource_path).decode("utf-8")
            for animation in text.animations(resource).values():
                for frame in _frames(resource, animation):
                    if resource.count(frame["texture"].text(resource)) > 1:
                        return reconcile(exporter, plan, source, manifest)

    # The minimal path retains exact record formatting for known atlas mappings.
    # Reconcile differing Godot shapes against a fresh plan rather than denying export.
    original = copy.deepcopy(plan)
    try:
        return _minimal_update(exporter, plan, source, copy.deepcopy(manifest))
    except ValueError:
        return reconcile(exporter, original, source, manifest)


def prepare_export(exporter: "GodotSpriteExporter") -> ExportPlan:
    root = exporter.output_dir
    plan = ExportPlan(root=root, exported_dirs=[root])
    plan.inputs.update(getattr(exporter, "recovery_inputs", {}))
    stage_pending_recovery(plan)
    source = _source(exporter, plan)
    manifest_path = root / MANIFEST
    plan.guards[manifest_path] = manifest_path.read_bytes() if manifest_path.exists() else None
    if not _exists(plan, manifest_path):
        result = _adopt(exporter, plan, source)
    else:
        try:
            manifest = json.loads(_read(plan, manifest_path))
        except (json.JSONDecodeError, UnicodeDecodeError):
            manifest = None
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") != 1
            or not all(key in manifest for key in ("source", "slots", "delivered"))
        ):
            plan.notices.append(
                "The prior export record cannot be used. Rebuild the source baseline while preserving current Godot values; review the proposed artwork changes."
            )
            result = _adopt(exporter, plan, source)
        else:
            result = _update(exporter, plan, source, manifest)
    return review_candidates(result)

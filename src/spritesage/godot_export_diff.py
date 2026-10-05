"""Compare staged artifacts with destination bytes before offering acceptance."""

import difflib
import io
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

from .godot_export_transaction import ExportPlan
from . import godot_text as text


def _brief(value):
    return value if len(value) < 100 else value[:97] + "..."


def _shape(source):
    """Enumerate all serialized sections/properties; keep Variant values opaque."""
    result = {}
    for section in text.sections(source):
        attrs = section.attributes
        identity = (
            section.kind + ":" + "/".join(attrs.get(key, "") for key in ("parent", "name", "id"))
        )
        if section.kind == "node" and "parent" not in attrs:
            identity = "node:Sprite"
        for key, value in attrs.items():
            if key not in ("load_steps", "id", "uid"):
                result[(identity, key)] = value
        for key, span in section.properties.items():
            if key != "animations":
                result[(identity, key)] = span.text(source)
            elif section.kind == "sub_resource":
                for record in text.items(source, span):
                    animation = text.fields(source, record)
                    name = json.loads(animation["name"].text(source).removeprefix("&"))
                    for field, value in animation.items():
                        if field != "frames":
                            result[("animation:" + name, field)] = value.text(source)
                    frames = text.items(source, animation["frames"])
                    result[("animation:" + name, "frame count")] = str(len(frames))
                    for index, frame in enumerate(frames):
                        for field, value in text.fields(source, frame).items():
                            result[("animation:" + name, f"frame {index + 1} {field}")] = (
                                value.text(source)
                            )
    return result


def _human_text_diff(before, after):
    changes = []
    old_shape, new_shape = _shape(before), _shape(after)
    for identity, key in sorted(old_shape.keys() | new_shape.keys()):
        old, new = old_shape.get((identity, key)), new_shape.get((identity, key))
        if old == new:
            continue
        label = (
            key
            if identity.startswith(("gd_scene:", "gd_resource:", "resource:"))
            else identity.split(":", 1)[1].strip("/").replace('"', "") + ": " + key
        )
        if old is None:
            changes.append(f"Add {label}: {_brief(new)}")
        elif new is None:
            changes.append(f"Remove {label}: {_brief(old)}")
        else:
            changes.append(f"{label}: {_brief(old)} \u2192 {_brief(new)}")
    try:
        previous, incoming = text.animations(before), text.animations(after)
    except ValueError:
        # Scene properties (including inline SpriteFrames) are still enumerated
        # in their original resource sections above.
        return changes
    renamed = set()
    for old_name in previous.keys() - incoming.keys():
        old_values = {
            key: value.text(before) for key, value in previous[old_name].items() if key != "name"
        }
        matches = [
            name
            for name in incoming.keys() - previous.keys()
            if {key: value.text(after) for key, value in incoming[name].items() if key != "name"}
            == old_values
        ]
        if len(matches) == 1:
            changes.append(f"Rename animation: {old_name} \\u2192 {matches[0]}")
            renamed.update((old_name, matches[0]))
    for name in sorted(previous.keys() | incoming.keys()):
        if name in renamed:
            continue
        if name not in previous:
            changes.append(f"Add animation: {name}")
            continue
        if name not in incoming:
            changes.append(f"Remove animation: {name}, including its frame properties")
            continue
        old, new = previous[name], incoming[name]
        for key in sorted(old.keys() | new.keys()):
            if key in ("frames", "name"):
                continue
            first, second = old[key].text(before) if key in old else "(absent)", (
                new[key].text(after) if key in new else "(absent)"
            )
            if first != second:
                changes.append(
                    f"{name}: {'FPS' if key == 'speed' else key}: {_brief(first)} \u2192 {_brief(second)}"
                )
        old_frames, new_frames = text.items(before, old["frames"]), text.items(after, new["frames"])
        if len(old_frames) != len(new_frames):
            changes.append(f"{name}: frame count: {len(old_frames)} \u2192 {len(new_frames)}")
        for index, (first, second) in enumerate(zip(old_frames, new_frames, strict=False)):
            old_fields, new_fields = text.fields(before, first), text.fields(after, second)
            for key in sorted(old_fields.keys() | new_fields.keys()):
                a = old_fields[key].text(before) if key in old_fields else "(absent)"
                b = new_fields[key].text(after) if key in new_fields else "(absent)"
                if a == b:
                    continue
                if key == "texture":
                    changes.append(f"{name}: frame {index + 1} image/reference changes")
                else:
                    changes.append(
                        f"{name}: frame {index + 1} {key}: {_brief(a)} \u2192 {_brief(b)}"
                    )
    return changes


def _image_difference(name, before, staged):
    with Image.open(staged) as proposed:
        try:
            original = Image.open(io.BytesIO(before))
        except OSError:
            return f"{name}: replace unreadable image ({len(before)} bytes) with {proposed.width}\u00d7{proposed.height} image"
        with original:
            difference = f"{name}: image {original.width}\u00d7{original.height} \u2192 {proposed.width}\u00d7{proposed.height}"
            if original.size == proposed.size:
                channels = ImageChops.difference(
                    original.convert("RGBA"), proposed.convert("RGBA")
                ).split()
                mask = channels[0]
                for channel in channels[1:]:
                    mask = ImageChops.lighter(mask, channel)
                difference += f"; changed pixel region: {mask.getbbox()}"
            return difference


def review_candidates(plan: ExportPlan) -> ExportPlan:
    """Stage exact proposed files; the preview and commit share the same bytes."""
    plan.deletes.difference_update(plan.writes)
    for destination in list(plan.deletes):
        before = plan.guards.get(destination)
        if before is None:
            plan.deletes.remove(destination)
            continue
        if destination.name.startswith(".spritesage-"):
            continue
        plan.file_diffs[destination] = f"Remove incomplete export file: {destination.name}"
        plan.file_summaries[destination] = [plan.file_diffs[destination]]
    with tempfile.TemporaryDirectory(prefix="spritesage-godot-review-") as directory:
        for index, (destination, content) in enumerate(list(plan.writes.items())):
            staged = Path(directory) / str(index) / destination.name
            staged.parent.mkdir(parents=True)
            staged.write_bytes(content)
            candidate = staged.read_bytes()
            before = plan.guards.setdefault(
                destination, destination.read_bytes() if destination.exists() else None
            )
            if before == candidate:
                del plan.writes[destination]
                continue
            plan.writes[destination] = candidate
            if destination.name.startswith(".spritesage-"):
                continue
            if before is None:
                plan.file_diffs[destination] = f"Create {destination.name}"
                plan.file_summaries[destination] = [f"Create {destination.name}"]
                continue
            if destination.suffix.lower() in (".tscn", ".tres"):
                plan.file_summaries[destination] = _human_text_diff(
                    before.decode("utf-8", errors="replace"), candidate.decode("utf-8")
                )
                difference = "".join(
                    difflib.unified_diff(
                        before.decode("utf-8", errors="replace").splitlines(keepends=True),
                        candidate.decode("utf-8").splitlines(keepends=True),
                        fromfile=f"Existing/{destination.name}",
                        tofile=f"Proposed/{destination.name}",
                    )
                )
            else:
                difference = _image_difference(destination.name, before, staged)
            plan.file_diffs[destination] = difference
            plan.file_summaries.setdefault(destination, [difference])
            if not plan.updates:
                plan.updates.append(f"{destination.name}: update existing Godot asset")
    if not any(plan.guards[path] is not None for path in plan.file_diffs):
        plan.updates.clear()
        plan.conflicts.clear()
    return plan

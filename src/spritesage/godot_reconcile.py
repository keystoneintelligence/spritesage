"""Reconcile source intentions with authored Godot 4 text resources.

SpriteFrames animation/frame dictionaries, AtlasTexture references, and the
exported sprite node are owned fields. Everything else is retained verbatim,
including arbitrary Variant metadata and unrelated resource/node sections.
"""

import copy
import json
import re
import uuid

from PIL import Image

from . import godot_text as text
from .godot_preservation import (
    MANIFEST,
    _read,
    _png,
    _pixels,
    _image,
    _frames,
    _frame_mapping,
    _manifest_bytes,
    _region,
    _playback,
    _resolve_reference,
)


def _quote(value):
    return json.dumps(value, ensure_ascii=False)


def _root(scene):
    # Godot authors can wrap the exported visual in a gameplay root. Select
    # the bound sprite, so changing its filter/binding never rewrites that root.
    nodes = [section for section in text.sections(scene) if section.kind == "node"]
    bound = [
        section
        for section in nodes
        if "sprite_frames" in section.properties or "texture" in section.properties
    ]
    return next(
        (
            section
            for section in bound
            if section.attributes.get("type") in ('"AnimatedSprite2D"', '"Sprite2D"')
        ),
        (
            bound[0]
            if bound
            else next(section for section in nodes if "parent" not in section.attributes)
        ),
    )


def _put_property(source, section, key, value):
    span = section.properties.get(key)
    if span:
        return text.patch(source, [(span, value)])
    return text.patch(
        source, [(text.Span(section.body.start, section.body.start), f"{key} = {value}\n")]
    )


def _steps(resource):
    steps = 1 + sum(s.kind in ("sub_resource", "ext_resource") for s in text.sections(resource))
    return re.sub(
        r"(?m)^(\[gd_(?:resource|scene)[^\n]*?\bload_steps=)\d+",
        lambda m: m[1] + str(steps),
        resource,
        count=1,
    )


def _bind(scene, target, property_name, resource_type, plan):
    """Repair only the exported sprite's binding, preserving every other field."""
    root = _root(scene)
    current = root.properties.get(property_name)
    if current:
        match = re.fullmatch(r'ExtResource\("([^"]+)"\)', current.text(scene))
        if match:
            ext = next(
                (
                    s
                    for s in text.sections(scene)
                    if s.kind == "ext_resource" and s.attributes.get("id") == _quote(match[1])
                ),
                None,
            )
            if ext:
                reference = json.loads(ext.attributes.get("path", '""'))
                try:
                    if _resolve_reference(reference, target) == target.resolve():
                        return scene
                except ValueError:
                    pass
                header = ext.header.text(scene)
                header = re.sub(r'\bpath="(?:[^"\\]|\\.)*"', "path=" + _quote(target.name), header)
                # Retain the actual resource UID when rebinding to that resource.
                header = re.sub(r'\s+uid="[^"]+"', "", header)
                if header != ext.header.text(scene):
                    plan.updates.append(f"{target.name}: reconnect scene resource binding")
                    plan.conflicts.append(plan.updates[-1])
                return text.patch(scene, [(ext.header, header)])
    identifier = "SpriteSage_" + uuid.uuid4().hex[:8]
    header = (
        f'[ext_resource type="{resource_type}" path={_quote(target.name)} id="{identifier}"]\n\n'
    )
    scene = _put_property(scene, root, property_name, f'ExtResource("{identifier}")')
    root = _root(scene)
    scene = text.patch(scene, [(text.Span(root.header.start, root.header.start), header)])
    plan.updates.append(f"{target.name}: reconnect scene resource binding")
    plan.conflicts.append(plan.updates[-1])
    return _steps(scene)


def _renames(old, source):
    removed = set(old) - set(source)
    added = set(source) - set(old)
    result = {}
    for name in sorted(added):
        matches = [
            before
            for before in sorted(removed)
            if [frame["path"] for frame in old[before]["frames"]]
            == [frame["path"] for frame in source[name]["frames"]]
        ]
        if len(matches) == 1:
            result[name] = matches[0]
            removed.remove(matches[0])
    return result


def _texture(frame, resource):
    return frame["texture"].text(resource)


def _current_mapping(resource, records, slots, sheet_path):
    frames = [text.fields(resource, record) for record in records]
    result = []
    available = set(range(len(records)))
    for old_index, slot in enumerate(slots):
        matches = [
            i for i in sorted(available) if slot.get("texture") == _texture(frames[i], resource)
        ]
        if not matches:
            for i in sorted(available):
                try:
                    if list(_region(resource, frames[i], sheet_path)) == slot["region"]:
                        matches.append(i)
                except ValueError:
                    pass
            # Upgrade older records lacking reference identities without guessing
            # across reordered, ambiguous textures. Unmatched changes get a new cell.
        chosen = (old_index if old_index in matches else matches[0]) if matches else None
        result.append(chosen)
        if chosen is not None:
            available.remove(chosen)
    missing = [index for index, position in enumerate(result) if position is None]
    if len(missing) == 1 and len(available) == 1 and len(slots) == len(records):
        # Every other stable reference establishes the sole surviving frame.
        result[missing[0]] = available.pop()
    return result, available


def _animate_static(exporter, plan, source, scene, physical_name):
    from .godot_preservation import _new
    from .godot_export_transaction import ExportPlan

    staged_exporter = copy.copy(exporter)
    staged_exporter.asset_name = physical_name
    generated = _new(staged_exporter, ExportPlan(root=plan.root), source)
    for path, content in generated.writes.items():
        if path.suffix != ".tscn":
            plan.writes[path] = content
    node = _root(scene)
    header = re.sub(r'\btype="[^"]+"', 'type="AnimatedSprite2D"', node.header.text(scene))
    scene = text.patch(scene, [(node.header, header)])
    for key in (
        "texture",
        "hframes",
        "vframes",
        "region_enabled",
        "region_rect",
        "region_filter_clip_enabled",
        "frame_coords",
        "frame",
    ):
        node = _root(scene)
        span = node.properties.get(key)
        if span:
            start = scene.rfind("\n", 0, span.start) + 1
            end = scene.find("\n", span.end)
            scene = text.patch(
                scene, [(text.Span(start, len(scene) if end == -1 else end + 1), "")]
            )
            plan.updates.append(f"Animated sprite: remove static {key} property")
    scene = _bind(
        scene, plan.root / f"{physical_name}_frames.tres", "sprite_frames", "SpriteFrames", plan
    )
    scene = _put_property(
        scene, _root(scene), "animation", "&" + _quote(next(iter(source["animations"])))
    )
    plan.writes[plan.root / f"{physical_name}.tscn"] = scene.encode("utf-8")
    manifest = json.loads(plan.writes[plan.root / MANIFEST])
    manifest["asset_file_name"] = physical_name
    plan.writes[plan.root / MANIFEST] = _manifest_bytes(manifest)
    plan.updates.append("Sprite node: Sprite2D \u2192 AnimatedSprite2D; add animation playback")
    plan.notices.append(
        "Scripts, collision shapes, metadata and child nodes are retained. Review scripts that depend on the Sprite2D class after adding animation."
    )
    return plan


def reconcile(exporter, plan, source, manifest):
    """Build a reviewable candidate even when either app changed the asset shape."""
    root = exporter.output_dir
    manifest = copy.deepcopy(manifest)
    old = manifest["source"]
    physical_name = manifest.get("asset_file_name", old["asset_name"])
    manifest["asset_file_name"] = physical_name
    scene_path = root / f"{physical_name}.tscn"
    scene = _read(plan, scene_path).decode("utf-8")
    original_scene = scene
    node = _root(scene)
    if source["pixel_art"] != old["pixel_art"]:
        desired = "1" if source["pixel_art"] else "2"
        current = node.properties.get("texture_filter")
        if current is None or current.text(scene) != desired:
            scene = _put_property(scene, node, "texture_filter", desired)
            plan.updates.append(
                f"{physical_name}: texture filtering → {'nearest' if source['pixel_art'] else 'linear'}"
            )
    if source["asset_name"] != old["asset_name"]:
        node = _root(scene)
        header = re.sub(
            r'\bname="(?:[^"\\]|\\.)*"',
            "name=" + _quote(source["asset_name"]),
            node.header.text(scene),
            count=1,
        )
        scene = text.patch(scene, [(node.header, header)])
        plan.updates.append(
            f"Sprite name: {old['asset_name']} → {source['asset_name']}; retain existing file paths"
        )
        plan.notices.append(
            "Scene file paths remain stable. Review scripts that refer to the renamed sprite node."
        )
    if source["uuid"] != old["uuid"]:
        plan.updates.append("Use this sprite as the source for the existing Godot asset")
    resized = source["size"] != old["size"]
    if resized:
        plan.updates.append(
            f"Frame canvas: {old['size'][0]}×{old['size'][1]} → {source['size'][0]}×{source['size'][1]}"
        )
        plan.notices.append(
            "Collision shapes, offsets, scripts and metadata keep their authored values. Review their alignment with the resized artwork."
        )
    if "base_hash" in manifest and exporter.frame_count:
        return _animate_static(exporter, plan, source, scene, physical_name)
    if "base_hash" in manifest and not exporter.frame_count:
        image_path = root / manifest.get("base_file", f"{physical_name}.png")
        image_path.resolve().relative_to(root.resolve())
        scene = _bind(scene, image_path, "texture", "Texture2D", plan)
        if source.get("base") != old.get("base"):
            destination = _image(image_path, plan)
            _read(plan, image_path)
            replacement = exporter.render_base_image()
            if _pixels(destination) != _pixels(replacement):
                plan.writes[image_path] = _png(replacement)
                plan.updates.append(f"{physical_name}: replace sprite image")
            manifest["base_hash"] = _pixels(replacement)
    else:
        resource_path = root / manifest.get("resource_file", f"{physical_name}_frames.tres")
        managed_resource_path = resource_path
        external_resource = False
        binding = _root(scene).properties.get("sprite_frames")
        if binding:
            reference = re.fullmatch(r'ExtResource\("([^"]+)"\)', binding.text(scene))
            if reference:
                external = next(
                    (
                        s
                        for s in text.sections(scene)
                        if s.kind == "ext_resource"
                        and s.attributes.get("id") == _quote(reference[1])
                    ),
                    None,
                )
                if external and "path" in external.attributes:
                    try:
                        bound_path = _resolve_reference(
                            json.loads(external.attributes["path"]), resource_path
                        )
                        if bound_path.is_file():
                            resource_path = bound_path
                            external_resource = not bound_path.is_relative_to(root.resolve())
                    except ValueError:
                        pass
        inline = None
        if binding:
            reference = re.fullmatch(r'SubResource\("([^"]+)"\)', binding.text(scene))
            if reference:
                inline = next(
                    (
                        s
                        for s in text.sections(scene)
                        if s.kind == "sub_resource"
                        and s.attributes.get("id") == _quote(reference[1])
                        and s.attributes.get("type") == '"SpriteFrames"'
                    ),
                    None,
                )
        if inline:
            inline_header = inline.header.text(scene)
            resource = text.patch(scene, [(inline.header, "[resource]\n")])
            manifest["inline_frames"] = json.loads(inline.attributes["id"])
        else:
            manifest.pop("inline_frames", None)
            manifest["resource_file"] = (
                managed_resource_path.relative_to(root.resolve()).as_posix()
                if managed_resource_path.is_absolute()
                else managed_resource_path.relative_to(root).as_posix()
            )
            scene = _bind(scene, resource_path, "sprite_frames", "SpriteFrames", plan)
            resource = _read(plan, resource_path).decode("utf-8")
        original_resource = resource
        animations = text.animations(resource)
        animation_spans = text.animation_records(resource)
        sheet_path = root / f"{physical_name}_sheet.png"
        _read(plan, sheet_path)
        sheet = _image(sheet_path, plan)
        append_y = sheet.height
        atlases = []
        atlas_updates = {}
        image_changed = False
        rendered = {}
        sheet_ext = None
        for external in text.sections(resource):
            if external.kind != "ext_resource" or "path" not in external.attributes:
                continue
            try:
                if (
                    _resolve_reference(json.loads(external.attributes["path"]), sheet_path)
                    == sheet_path.resolve()
                ):
                    sheet_ext = external.attributes["id"]
                    break
            except ValueError:
                continue
        if sheet_ext is None:
            sheet_ext = _quote("SpriteSage_" + uuid.uuid4().hex[:8])
            atlases.append(
                f'[ext_resource type="Texture2D" path={_quote(sheet_path.name)} id={sheet_ext}]\n\n'
            )

        def render(path):
            if path not in rendered:
                rendered[path] = exporter.sheet_gen.render_frames(
                    [path], exporter.progress_callback
                )[0][0]
            return rendered[path]

        def append_image(incoming, template_texture=None):
            nonlocal sheet, append_y, image_changed
            replacement = render(incoming["path"])
            w, h = replacement.size
            y = append_y
            append_y += h
            expanded = Image.new(
                "RGBA",
                (
                    exporter.sheet_gen.next_power_of_two(max(sheet.width, w)),
                    exporter.sheet_gen.next_power_of_two(append_y),
                ),
            )
            expanded.paste(sheet, (0, 0))
            expanded.paste(replacement, (0, y))
            sheet = expanded
            image_changed = True
            identifier = "AtlasTexture_" + uuid.uuid4().hex[:12]
            template = None
            match = re.fullmatch(r'SubResource\("([^"]+)"\)', template_texture or "")
            if match:
                template = next(
                    (
                        section
                        for section in text.sections(resource)
                        if section.kind == "sub_resource"
                        and section.attributes.get("id") == _quote(match[1])
                        and section.attributes.get("type") == '"AtlasTexture"'
                    ),
                    None,
                )
            if template and match and template_texture and resource.count(template_texture) == 1:
                # Move the private atlas cell without changing its resource identity
                # or any authored texture properties.
                identifier = match[1]
                atlas_updates[_quote(identifier)] = {
                    "atlas": f"ExtResource({sheet_ext})",
                    "region": f"Rect2(0, {y}, {w}, {h})",
                }
            else:
                if template:
                    block = resource[template.header.start : template.body.end]
                    section = text.sections(block)[0]
                    header = re.sub(
                        r'\bid="[^"]+"', 'id="' + identifier + '"', section.header.text(block)
                    )
                    block = text.patch(block, [(section.header, header)])
                    block = _put_property(
                        block, text.sections(block)[0], "atlas", f"ExtResource({sheet_ext})"
                    )
                    block = _put_property(
                        block, text.sections(block)[0], "region", f"Rect2(0, {y}, {w}, {h})"
                    )
                else:
                    block = f'[sub_resource type="AtlasTexture" id="{identifier}"]\natlas = ExtResource({sheet_ext})\nregion = Rect2(0, {y}, {w}, {h})\n\n'
                atlases.append(block)
            return f'SubResource("{identifier}")', {
                "id": uuid.uuid4().hex,
                "region": [0, y, w, h],
                "hash": _pixels(replacement),
                "texture": f'SubResource("{identifier}")',
            }

        old_animations = old["animations"]
        renames = _renames(old_animations, source["animations"])
        removed = set(old_animations) - set(source["animations"]) - set(renames.values())
        updates = {}
        new_slots = dict(manifest["slots"])
        delivered = manifest["delivered"]
        animation_targets = {}
        for name in sorted(removed):
            if name in animations:
                plan.updates.append(f"Remove animation: {name}")
                plan.conflicts.append(
                    f"{name}: remove animation, including its Godot settings and frame metadata"
                )
                plan.notices.append(
                    f"{name}: scripts, event tracks and metadata remain authored; review references to the removed animation."
                )
            new_slots.pop(name, None)
        for name, animation in source["animations"].items():
            before_name = renames.get(name, name)
            previous = old_animations.get(before_name)
            target_name = manifest.get("animation_targets", {}).get(before_name, before_name)
            if target_name not in animations:
                target_name = name
                expected = {
                    slot.get("texture") for slot in manifest["slots"].get(before_name, [])
                } - {None}
                matches = [
                    candidate_name
                    for candidate_name, candidate in animations.items()
                    if expected
                    and {_texture(frame, resource) for frame in _frames(resource, candidate)}
                    == expected
                ]
                if len(matches) == 1:
                    target_name = matches[0]
            animation_targets[name] = name if name in renames else target_name
            target = animations.get(target_name)
            # Untouched animations deleted/renamed in Godot remain authored.
            if previous == animation and name not in renames and not resized:
                continue
            fresh = target is None
            record = (
                animation_spans[target_name].text(resource)
                if target
                else f'{{"frames": [], "loop": {str(animation["loop"]).lower()}, "name": &{_quote(name)}, "speed": {animation["fps"]}}}'
            )
            fields = text.fields(record, text.Span(0, len(record)))
            current_fps = float(text.scalar(record, fields["speed"], allow_zero=True))
            edits = []
            if name in renames:
                edits.append((fields["name"], "&" + _quote(name)))
                plan.updates.append(f"Rename animation: {before_name} → {name}")
                plan.notices.append(
                    f"{before_name} → {name}: scripts and event tracks remain authored; review animation-name references."
                )
                new_slots.pop(before_name, None)
            for prop, target_prop in (("fps", "speed"), ("loop", "loop")):
                if previous and animation[prop] != previous[prop]:
                    current = text.scalar(record, fields[target_prop], allow_zero=prop == "fps")
                    if current != animation[prop]:
                        edits.append((fields[target_prop], str(animation[prop]).lower()))
                        plan.updates.append(f"{name}: {prop}: {current} → {animation[prop]}")
                        if current != delivered.get(before_name, {}).get(prop):
                            plan.conflicts.append(plan.updates[-1])
                        if prop == "fps":
                            current_fps = animation[prop]
            current_records = text.items(record, fields["frames"])
            current_fields = [text.fields(record, s) for s in current_records]
            slots = manifest["slots"].get(before_name, [])
            # Map baseline identities to current Godot frames, including reordering.
            positions, extras = _current_mapping(
                record if fresh else resource,
                [] if fresh else text.items(resource, target["frames"]),
                slots,
                sheet_path,
            )
            mapping = (
                _frame_mapping(previous["frames"], animation["frames"])
                if previous
                else [None] * len(animation["frames"])
            )
            structural = previous is None or mapping != list(range(len(previous["frames"])))
            new_records, kept_positions, result_slots = [], [], []
            for index, (incoming, old_index) in enumerate(
                zip(animation["frames"], mapping, strict=True)
            ):
                position = (
                    positions[old_index]
                    if old_index is not None and old_index < len(positions)
                    else None
                )
                before = (
                    previous["frames"][old_index] if previous and old_index is not None else None
                )
                changed_image = (
                    fresh or resized or before is None or incoming["hash"] != before["hash"]
                )
                changed_hold = before is None or incoming["hold"] != before["hold"]
                if position is None:
                    if changed_hold:
                        changed_image = True
                    if changed_image:
                        changed_hold = True
                if position is None and not changed_image and not changed_hold:
                    result_slots.append(dict(slots[old_index]))
                    continue
                frame_record = (
                    current_records[position].text(record)
                    if position is not None
                    else '{"duration": 1, "texture": null}'
                )
                frame = text.fields(frame_record, text.Span(0, len(frame_record)))
                frame_edits = []
                slot = (
                    dict(slots[old_index])
                    if old_index is not None and old_index < len(slots)
                    else None
                )
                if changed_image:
                    replacement = render(incoming["path"])
                    try:
                        region = (
                            _region(
                                original_resource,
                                _frames(original_resource, target)[position],
                                sheet_path,
                            )
                            if position is not None and target is not None
                            else None
                        )
                    except ValueError:
                        region = None
                    can_replace_cell = (
                        region is not None
                        and slot is not None
                        and list(region) == slot["region"]
                        and replacement.size == tuple(region[2:])
                        and position is not None
                        and original_resource.count(
                            current_fields[position]["texture"].text(record)
                        )
                        == 1
                        and region[0] >= 0
                        and region[1] >= 0
                        and region[0] + region[2] <= sheet.width
                        and region[1] + region[3] <= sheet.height
                    )
                    if can_replace_cell:
                        assert region is not None and slot is not None
                        x, y, w, h = region
                        actual = _pixels(sheet.crop((x, y, x + w, y + h)))
                        if actual != _pixels(replacement):
                            sheet.paste(replacement, (x, y))
                            image_changed = True
                            plan.updates.append(f"{name}: replace frame {index + 1} image")
                            if actual != slot["hash"]:
                                plan.conflicts.append(plan.updates[-1])
                        slot["hash"] = _pixels(replacement)
                    else:
                        mapping_changed = position is not None and (
                            region is None
                            or slot is None
                            or list(region) != slot["region"]
                            or frame["texture"].text(frame_record) != slot.get("texture")
                        )
                        texture, slot = append_image(incoming, frame["texture"].text(frame_record))
                        frame_edits.append((frame["texture"], texture))
                        plan.updates.append(
                            f"{name}: {'replace' if position is not None else 'add'} frame {index + 1} image"
                        )
                        if mapping_changed:
                            plan.conflicts.append(
                                f"{name}: frame {index + 1} texture mapping changed in Godot; update this frame's atlas cell/binding"
                            )
                if changed_hold:
                    desired = (
                        incoming["hold"] * current_fps / animation["fps"]
                        if current_fps
                        else incoming["hold"]
                    )
                    actual = float(text.scalar(frame_record, frame["duration"], allow_zero=True))
                    if actual != desired:
                        frame_edits.append((frame["duration"], f"{desired:.12g}"))
                        plan.updates.append(
                            f"{name}: frame {index + 1} duration → {incoming['hold'] / animation['fps'] * 1000:.12g} ms"
                        )
                        if (
                            position is not None
                            and old_index is not None
                            and actual
                            != (
                                delivered.get(before_name, {}).get("holds", [])
                                + [None] * (old_index + 1)
                            )[old_index]
                        ):
                            plan.conflicts.append(plan.updates[-1])
                    if current_fps == 0:
                        plan.notices.append(
                            f"{name}: animation remains paused at 0 FPS; updated duration is stored as a frame weight at the SpriteSage time base ({animation['fps']} FPS). Playback stays paused until you resume it in Godot."
                        )
                new_records.append(text.patch(frame_record, frame_edits))
                kept_positions.append(position)
                if slot is not None:
                    slot["texture"] = text.fields(
                        new_records[-1], text.Span(0, len(new_records[-1]))
                    )["texture"].text(new_records[-1])
                    result_slots.append(slot)
            # Preserve Godot-only frames and ordering unless SpriteSage changed the sequence.
            if not structural and not fresh:
                ordered = {
                    position: entry
                    for position, entry in zip(kept_positions, new_records, strict=True)
                    if position is not None
                }
                appended = [
                    entry
                    for position, entry in zip(kept_positions, new_records, strict=True)
                    if position is None
                ]
                new_records = [
                    ordered.get(i, entry.text(record)) for i, entry in enumerate(current_records)
                ] + appended
            else:
                new_records.extend(current_records[i].text(record) for i in sorted(extras))
                if previous:
                    plan.updates.append(
                        f"{name}: frame count: {len(current_records)} → {len(new_records)}; update frame order/list"
                    )
                    plan.notices.append(
                        f"{name}: frame-index metadata, scripts and event tracks remain as authored. Review their references after changing the frame list."
                    )
            current_values = [s.text(record) for s in current_records]
            if current_values != new_records:
                edits.append((fields["frames"], "[\n" + ",\n".join(new_records) + "\n]"))
            new_record = text.patch(record, edits)
            updates[target_name] = new_record
            new_slots[name] = result_slots
            if fresh:
                plan.updates.append(f"{name}: {'restore' if previous else 'add'} animation")
        array = text.animations_span(resource)
        records = []
        for name, span in animation_spans.items():
            if name not in removed:
                records.append(updates.pop(name, span.text(resource)))
        records.extend(updates.values())
        old_records = [s.text(resource) for s in text.items(resource, array)]
        if records != old_records:
            # Change only altered animation dictionaries, avoiding array reformatting
            # when membership is unchanged.
            if len(records) == len(old_records) and not removed and not updates:
                edits = [
                    (span, replacement)
                    for span, replacement in zip(text.items(resource, array), records, strict=True)
                    if span.text(resource) != replacement
                ]
                resource = text.patch(resource, edits)
            else:
                resource = text.patch(resource, [(array, "[\n" + ",\n".join(records) + "\n]")])
        for identifier, properties in atlas_updates.items():
            for key, value in properties.items():
                section = next(
                    section
                    for section in text.sections(resource)
                    if section.kind == "sub_resource" and section.attributes.get("id") == identifier
                )
                resource = _put_property(resource, section, key, value)
        if atlases:
            sections = text.sections(resource)
            section = next(s for s in sections if s.kind == "resource")
            external_blocks = "".join(
                block for block in atlases if block.startswith("[ext_resource")
            )
            atlas_blocks = "".join(block for block in atlases if block.startswith("[sub_resource"))
            first_sub = min(
                (s.header.start for s in sections if s.kind == "sub_resource"),
                default=section.header.start,
            )
            first_sub = min(first_sub, section.header.start)
            if first_sub == section.header.start:
                additions = [(text.Span(first_sub, first_sub), external_blocks + atlas_blocks)]
            else:
                additions = [
                    (text.Span(first_sub, first_sub), external_blocks),
                    (text.Span(section.header.start, section.header.start), atlas_blocks),
                ]
            resource = text.patch(resource, additions)
            resource = _steps(resource)
        if inline:
            section = next(s for s in text.sections(resource) if s.kind == "resource")
            scene = text.patch(resource, [(section.header, inline_header)])
            if atlases:
                scene = _steps(scene)
        elif resource != original_resource:
            if external_resource:
                reference_edits = []
                for section in text.sections(resource):
                    if section.kind != "ext_resource" or "path" not in section.attributes:
                        continue
                    reference = json.loads(section.attributes["path"])
                    if reference.startswith("res://"):
                        continue
                    actual = _resolve_reference(reference, resource_path)
                    project_root = next(
                        (
                            parent
                            for parent in root.absolute().parents
                            if (parent / "project.godot").exists()
                        ),
                        None,
                    )
                    rebased = (
                        "res://" + actual.relative_to(project_root).as_posix()
                        if project_root and actual.is_relative_to(project_root)
                        else actual.as_posix()
                    )
                    header = re.sub(
                        r'\bpath="(?:[^"\\]|\\.)*"',
                        "path=" + _quote(rebased),
                        section.header.text(resource),
                    )
                    reference_edits.append((section.header, header))
                resource = text.patch(resource, reference_edits)
                canonical = (
                    _read(plan, managed_resource_path).decode("utf-8")
                    if managed_resource_path.exists()
                    else ""
                )
                original_uid = re.search(r'\buid="([^"]+)"', canonical)
                uid = original_uid[1] if original_uid else "uid://" + uuid.uuid4().hex[:12]
                resource = re.sub(
                    r'(?m)^(\[gd_resource[^\n]*\buid=")[^"]+"',
                    lambda m: m[1] + uid + '"',
                    resource,
                    count=1,
                )
                resource_path = managed_resource_path
                scene = _bind(scene, resource_path, "sprite_frames", "SpriteFrames", plan)
                plan.notices.append(
                    "The externally bound resource remains untouched. The scene will use a local copy retaining its authored settings and metadata, with the listed changes."
                )
            plan.writes[resource_path] = resource.encode("utf-8")
        if image_changed:
            plan.writes[sheet_path] = _png(sheet)
        manifest["slots"] = new_slots
        manifest["animation_targets"] = animation_targets
        manifest["delivered"] = _playback(resource)
        for source_name, actual_name in animation_targets.items():
            if actual_name in manifest["delivered"]:
                manifest["delivered"][source_name] = copy.deepcopy(
                    manifest["delivered"][actual_name]
                )
        current_animations = text.animations(resource)
        for name, slots in new_slots.items():
            actual_name = animation_targets.get(name, name)
            if actual_name not in current_animations:
                continue
            current = _frames(resource, current_animations[actual_name])
            positions, _ = _current_mapping(
                resource,
                text.items(resource, current_animations[actual_name]["frames"]),
                slots,
                sheet_path,
            )
            baseline = delivered.get(name, {}).get("holds", [])
            manifest["delivered"][name]["holds"] = [
                (
                    float(text.scalar(resource, current[position]["duration"], allow_zero=True))
                    if position is not None
                    else (baseline + [1] * len(slots))[index]
                )
                for index, position in enumerate(positions)
            ]
        # Repair only scene references invalidated by explicit source rename/removal.
        for property_name in ("animation", "autoplay"):
            node = _root(scene)
            span = node.properties.get(property_name)
            if span is None:
                continue
            current = json.loads(span.text(scene).removeprefix("&"))
            rename_targets = {before: after for after, before in renames.items()}
            if current in rename_targets or current in removed:
                desired = rename_targets.get(current, next(iter(manifest["delivered"]), ""))
                if desired:
                    scene = text.patch(
                        scene,
                        [
                            (
                                span,
                                (
                                    "&" + _quote(desired)
                                    if property_name == "animation"
                                    else _quote(desired)
                                ),
                            )
                        ],
                    )
                else:
                    start = scene.rfind("\n", 0, span.start) + 1
                    end = scene.find("\n", span.end)
                    scene = text.patch(
                        scene, [(text.Span(start, len(scene) if end == -1 else end + 1), "")]
                    )
                plan.updates.append(
                    f"Scene {property_name}: {current} \u2192 {desired or '(none)'}"
                )
    if scene != original_scene:
        plan.writes[scene_path] = scene.encode("utf-8")
    manifest["source"] = source
    plan.writes[root / MANIFEST] = _manifest_bytes(manifest)
    return plan

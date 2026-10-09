"""Lightweight, non-committable Godot review before background removal."""

import json
import re

from PIL import Image

from .exporter import GodotSpriteExporter
from .spritesheet import SpriteSheetGenerator


class ReviewSheetGenerator(SpriteSheetGenerator):
    def render_frames(self, frames, progress_callback=None):
        # Layout and field edits use the same planner. Raw resized images suffice
        # for the review; accepted exports always use the production generator.
        rendered = []
        for path in frames:
            with Image.open(path) as source:
                rendered.append(self._resize_frame(source.convert("RGBA")))
        return rendered, 0


class ReviewSpriteExporter(GodotSpriteExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sheet_gen = ReviewSheetGenerator(self.sprite_file)

    def prepare(self):
        from .godot_preservation import MANIFEST, _frame_mapping

        from .godot_reconcile import _renames

        plan = super().prepare()
        plan.review_only = True
        manifest_path = self.output_dir / MANIFEST
        proposed = plan.writes.get(manifest_path)
        existing_asset = any(
            path.suffix.lower() in (".tscn", ".tres") and value is not None
            for path, value in plan.guards.items()
        )
        if proposed is not None and existing_asset:
            incoming = json.loads(proposed)["source"]
            try:
                old = json.loads(plan.guards.get(manifest_path) or b"null")["source"]
            except (ValueError, TypeError, KeyError):
                old = None
            # A model's output is not available yet. Always disclose explicitly
            # changed source art, even when raw pixels already match Godot.
            renames = _renames(old["animations"], incoming["animations"]) if old else {}
            for name, animation in incoming["animations"].items():
                previous = old["animations"].get(renames.get(name, name)) if old else None
                mapping = (
                    _frame_mapping(previous["frames"], animation["frames"])
                    if previous
                    else [None] * len(animation["frames"])
                )
                for index, (frame, position) in enumerate(
                    zip(animation["frames"], mapping, strict=True)
                ):
                    if (
                        position is not None
                        and previous is not None
                        and frame["hash"] == previous["frames"][position]["hash"]
                    ):
                        continue
                    change = f"{name}: {'add' if position is None and old else 'replace'} frame {index + 1} image"
                    if not any(
                        f"{name}: " in message and f"frame {index + 1} image" in message
                        for message in plan.updates
                    ):
                        plan.updates.append(change)
            if "base" in incoming and (
                not old or incoming["base"]["hash"] != old.get("base", {}).get("hash")
            ):
                change = f"{self.asset_name}: replace sprite image"
                if change not in plan.updates:
                    plan.updates.append(change)
        return plan

    def render_base_image(self):
        with Image.open(self.sprite_file.base_image) as image:
            return image.convert("RGBA")


def friendly_changes(changes):
    """Name animation operations instead of implementation fields/coordinates."""
    result = []
    for change in changes:
        if ": frame list (previous positions): " in change:
            change = change.split(": frame list", 1)[0] + ": Updated animation frame order"
        elif match := re.fullmatch(r"(.*): frame count: (\d+) \u2192 (\d+)(?:;.*)?", change):
            label, before, after = match.groups()
            delta = int(after) - int(before)
            if delta:
                change = (
                    f"{label}: {'Added' if delta > 0 else 'Removed'} "
                    f"{abs(delta)} animation frame{'s' if abs(delta) != 1 else ''} "
                    f"({before} \u2192 {after})"
                )
            else:
                change = f"{label}: Updated animation frame order"
        elif match := re.fullmatch(r"(.*): remove frames: (.*)", change):
            change = f"{match[1]}: Removed animation frames {match[2]}"
        elif match := re.fullmatch(r"(.*): (add|replace) frame (\d+) image", change):
            label, action, frame = match.groups()
            change = (
                f"{label}: Added animation frame {frame}"
                if action == "add"
                else f"{label}: Changed artwork for animation frame {frame}"
            )
        elif match := re.fullmatch(r"(.*): frame (\d+) duration(.*)", change):
            change = f"{match[1]}: Changed timing for animation frame {match[2]}{match[3]}"
        elif match := re.fullmatch(r"(.*): (?:fps|FPS)(:.*)", change):
            change = f"{match[1]}: Changed timing (FPS){match[2]}"
        elif match := re.fullmatch(r"(.*): loop(:.*)", change):
            change = f"{match[1]}: Changed looping{match[2]}"
        elif ": replace sprite image" in change:
            change = change.replace(": replace sprite image", ": Changed sprite artwork")
        elif match := re.fullmatch(r"(.*): (add|restore) animation", change):
            change = f"{match[1]}: {'Added' if match[2] == 'add' else 'Restored'} animation"
        if change not in result:
            result.append(change)
    return result

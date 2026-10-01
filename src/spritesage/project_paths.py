"""Keep saved project references connected when files or folders are renamed."""

import json
import os
from pathlib import Path

from .paths import remap_path, stored_asset_path
from .persistence import save_document


def remap_project_references(
    project_file: str, old_path: str, new_path: str, *, original_project_dir: str
) -> set[str]:
    project = Path(project_file)
    root = project.parent
    changed_files: set[str] = set()
    failures = []

    def remap(value):
        if not isinstance(value, str) or not value:
            return value
        original = os.path.abspath(os.path.join(original_project_dir, value.replace("\\", "/")))
        changed = remap_path(original, old_path, new_path)
        if changed == original:
            return value
        return stored_asset_path(changed, str(root))

    # Only touch known path fields; never rewrite descriptions or arbitrary JSON text.
    for path in [project, *root.rglob("*.sprite")]:
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            failures.append(f"{path.name}: {error}")
            continue
        if not isinstance(data, dict):
            continue
        before = json.dumps(data, sort_keys=True)
        if path == project:
            for key in ("Reference Images", "Hidden Sprites"):
                if isinstance(data.get(key), list):
                    data[key] = [remap(value) for value in data[key]]
        else:
            if "base_image" in data:
                data["base_image"] = remap(data["base_image"])
            animations = data.get("animations", {})
            if isinstance(animations, dict):
                for name, record in animations.items():
                    if isinstance(record, list):  # Version 1 sprite files.
                        animations[name] = [remap(value) for value in record]
                    elif isinstance(record, dict) and isinstance(record.get("frames"), list):
                        for frame in record["frames"]:
                            if isinstance(frame, dict) and "path" in frame:
                                frame["path"] = remap(frame["path"])
        if json.dumps(data, sort_keys=True) != before:
            try:
                save_document(path, data)
                changed_files.add(str(path))
            except (OSError, ValueError) as error:
                failures.append(f"{path.name}: {error}")
    if failures:
        raise OSError(
            "The rename completed, but some references could not be checked or updated:\n"
            + "\n".join(failures)
        )
    return changed_files

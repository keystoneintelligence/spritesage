"""User-configurable motion templates; no model paths or weights in application code."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from platformdirs import user_data_path

from spritesage.model_baker.animations import inspect_animations
from spritesage.persistence import atomic_write


@dataclass(frozen=True)
class MotionTemplate:
    id: str
    name: str
    character_type: str
    model_path: str


class TemplateLibrary:
    def __init__(self, path=None):
        self.path = Path(
            path or user_data_path("Sprite Sage", appauthor=False) / "animation-templates.json"
        )

    def load(self) -> list[MotionTemplate]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("This motion template catalog needs a newer Sprite Sage version.")
        return [MotionTemplate(**item) for item in data["templates"]]

    def register(self, model_path, *, name=None, character_type="Humanoid") -> MotionTemplate:
        path = Path(model_path).resolve()
        if path.suffix.lower() != ".glb" or not path.is_file():
            raise ValueError("Choose a self-contained animated GLB model.")
        clips = inspect_animations(path)
        if not clips or not any(clip.duration > 0 for clip in clips):
            raise ValueError("This model has no animation clips.")
        names = [clip.name for clip in clips]
        if len(set(names)) != len(names):
            raise ValueError("Animation names must be unique within a template.")
        template = MotionTemplate(
            hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            name or path.stem.replace("_", " ").title(),
            character_type.strip() or "Humanoid",
            str(path),
        )
        entries = [entry for entry in self.load() if entry.id != template.id]
        entries.append(template)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.path,
            json.dumps(
                {"version": 1, "templates": [asdict(e) for e in entries]}, indent=2
            ).encode(),
        )
        return template

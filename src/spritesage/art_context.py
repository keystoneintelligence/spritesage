"""Project style and sprite identity shared by every image-generation workflow."""

from dataclasses import dataclass
import os


def path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True)
class ArtContext:
    project_description: str = ""
    keywords: str = ""
    camera: str = ""
    sprite_description: str = ""
    project_images: tuple[str, ...] = ()
    sprite_images: tuple[str, ...] = ()
    pixel_art: bool | None = None
    width: int = 0
    height: int = 0

    @classmethod
    def from_project(cls, project, sprite=None):
        # Keep configured references even if missing: generation must report the
        # problem rather than silently weakening the style guidance.
        return cls(
            project_description=project.project_description,
            keywords=project.keywords,
            camera=project.camera,
            project_images=tuple(
                os.path.abspath(os.path.join(project.directory, path))
                for path in project.reference_images
                if path
            ),
            sprite_description=sprite.description if sprite else "",
            sprite_images=(
                (os.path.abspath(os.path.join(project.directory, sprite.base_image)),)
                if sprite and sprite.base_image
                else ()
            ),
            pixel_art=sprite.pixel_art if sprite else None,
            width=sprite.width if sprite else 0,
            height=sprite.height if sprite else 0,
        )

    @classmethod
    def from_dict(cls, values):
        values = dict(values)
        for name in ("project_images", "sprite_images"):
            values[name] = tuple(values.get(name, ()))
        return cls(**values)

    def reference_paths(self, primary=()) -> list[str]:
        # Preserve primary slots, even when two animation endpoints coincide.
        paths = list(primary)
        seen = {path_key(path) for path in paths}
        for path in (*self.sprite_images, *self.project_images):
            if path and path_key(path) not in seen:
                paths.append(path)
                seen.add(path_key(path))
        return paths

    def to_prompt(self, references=(), *, pose_camera=False) -> str:
        lines = []
        for label, value in (
            ("Project description", self.project_description),
            ("Project keywords", self.keywords),
            ("Sprite description", self.sprite_description),
        ):
            if value:
                lines.append(f"{label}: {value}")
        if self.camera and self.camera.strip().lower() not in {"none", "null"}:
            lines.append(f"Project camera perspective: {self.camera}")
        if pose_camera:
            lines.append(
                "For this frame, the pose guide and selected template view determine the camera "
                "and facing direction; use the project context for visual style."
            )
        if self.pixel_art is not None:
            lines.append(
                "Rendering: pixel art with crisp pixel edges and a consistent palette."
                if self.pixel_art
                else "Rendering: smooth artwork; preserve the reference drawing style without "
                "converting it to pixel art."
            )
        if self.width and self.height:
            lines.append(
                f"Target sprite canvas: {self.width} x {self.height} pixels. "
                "Keep the complete sprite visible with consistent proportions and framing."
            )
        sprite_keys = {path_key(path) for path in self.sprite_images}
        project_keys = {path_key(path) for path in self.project_images}
        for index, path in enumerate(references, 1):
            roles = []
            if path_key(path) in sprite_keys:
                roles.append(
                    "sprite identity: preserve its design, proportions, outfit and details"
                )
            if path_key(path) in project_keys:
                roles.append("project style: match palette, lighting, texture and rendering")
            if roles:
                lines.append(f"Image {index} (<image{index}>): " + "; ".join(roles) + ".")
        if self.project_images:
            lines.append(
                "Project references guide art style, not the sprite's identity or animation pose. "
                "Do not copy their scenery, characters, layouts or text into the sprite."
            )
        return "\n".join(lines)

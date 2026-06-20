from __future__ import annotations

from PIL import Image


def apply_style(image: Image.Image, style: str = "none", pixel_size: int = 4) -> Image.Image:
    """Apply the prototype style pass.

    `none` keeps the render unchanged. `pixel` is a local placeholder for the
    future AI stylization stage.
    """
    rgba = image.convert("RGBA")
    if style == "none":
        return rgba
    if style == "pixel":
        return pixelate(rgba, pixel_size=pixel_size)
    raise ValueError(f"Unknown style '{style}'")


def pixelate(image: Image.Image, pixel_size: int = 4) -> Image.Image:
    pixel_size = max(1, int(pixel_size))
    if pixel_size == 1:
        return image

    width, height = image.size
    small_size = (max(1, width // pixel_size), max(1, height // pixel_size))
    small = image.resize(small_size, Image.Resampling.BOX)
    return small.resize((width, height), Image.Resampling.NEAREST)

"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (c) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter


@dataclass(frozen=True)
class PolishOptions:
    clean_background: bool = True
    trim_padding: bool = True
    center_on_canvas: bool = True
    add_outline: bool = False
    alpha_threshold: int = 16
    background_threshold: int = 18
    outline_color: tuple[int, int, int, int] = (0, 0, 0, 255)


def polish_image(image: Image.Image, options: PolishOptions) -> Image.Image:
    original_size = image.size
    polished = image.convert("RGBA")

    if options.clean_background:
        polished = clean_background_with_ben2(
            polished,
            alpha_threshold=options.alpha_threshold,
            background_threshold=options.background_threshold,
        )

    if options.trim_padding:
        polished = trim_empty_padding(polished)

    if options.add_outline:
        polished = add_one_pixel_outline(polished, color=options.outline_color)

    if options.center_on_canvas:
        polished = center_on_canvas(polished, original_size)

    return polished


def clean_background_with_ben2(
    image: Image.Image,
    *,
    alpha_threshold: int = 16,
    background_threshold: int = 18,
) -> Image.Image:
    try:
        return _remove_background_with_ben2(image.convert("RGB"))
    except Exception as exc:
        print(f"BEN2 background removal failed; falling back to threshold cleanup: {exc}")
        return clean_background(
            image,
            alpha_threshold=alpha_threshold,
            background_threshold=background_threshold,
        )


def clean_background(
    image: Image.Image,
    *,
    alpha_threshold: int = 16,
    background_threshold: int = 18,
) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha_threshold = max(0, min(255, int(alpha_threshold)))
    background_threshold = max(0, min(255, int(background_threshold)))

    if _has_transparency(rgba):
        pixels = [(r, g, b, 0 if a <= alpha_threshold else a) for r, g, b, a in rgba.getdata()]
        cleaned = Image.new("RGBA", rgba.size)
        cleaned.putdata(pixels)
        return cleaned

    background = _estimate_edge_background(rgba)
    if background is None:
        return rgba

    br, bg, bb = background
    pixels = []
    for r, g, b, a in rgba.getdata():
        distance = max(abs(r - br), abs(g - bg), abs(b - bb))
        pixels.append((r, g, b, 0 if distance <= background_threshold else a))

    cleaned = Image.new("RGBA", rgba.size)
    cleaned.putdata(pixels)
    return cleaned


def trim_empty_padding(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return rgba
    return rgba.crop(bbox)


def center_on_canvas(image: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas_width, canvas_height = canvas_size
    if canvas_width <= 0 or canvas_height <= 0:
        return rgba

    if rgba.width > canvas_width or rgba.height > canvas_height:
        left = max(0, (rgba.width - canvas_width) // 2)
        top = max(0, (rgba.height - canvas_height) // 2)
        rgba = rgba.crop((left, top, left + canvas_width, top + canvas_height))

    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    paste_x = (canvas_width - rgba.width) // 2
    paste_y = (canvas_height - rgba.height) // 2
    canvas.alpha_composite(rgba, (paste_x, paste_y))
    return canvas


def add_one_pixel_outline(
    image: Image.Image,
    *,
    color: tuple[int, int, int, int] = (0, 0, 0, 255),
) -> Image.Image:
    source = image.convert("RGBA")
    rgba = Image.new("RGBA", (source.width + 2, source.height + 2), (0, 0, 0, 0))
    rgba.alpha_composite(source, (1, 1))
    alpha = rgba.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(3))
    outline_alpha = Image.new("L", rgba.size, 0)
    outline_alpha.paste(expanded)
    outline_alpha = Image.eval(
        outline_alpha,
        lambda value: 0 if value == 0 else 255,
    )
    outline_alpha = Image.composite(
        Image.new("L", rgba.size, 0),
        outline_alpha,
        alpha,
    )

    outline = Image.new("RGBA", rgba.size, color)
    outline.putalpha(outline_alpha)
    outline.alpha_composite(rgba)
    return outline


def save_polished_copy(source_path: str | Path, image: Image.Image) -> Path:
    source = Path(source_path)
    output_path = _unique_polished_path(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _unique_polished_path(source_path: Path) -> Path:
    suffix = source_path.suffix or ".png"
    base = source_path.with_suffix("")
    candidate = base.with_name(f"{base.name}_polished").with_suffix(suffix)
    index = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_polished_{index}").with_suffix(suffix)
        index += 1
    return candidate


def _has_transparency(image: Image.Image) -> bool:
    min_alpha, max_alpha = image.getchannel("A").getextrema()
    return min_alpha < 255 or max_alpha < 255


def _estimate_edge_background(image: Image.Image) -> tuple[int, int, int] | None:
    width, height = image.size
    if width == 0 or height == 0:
        return None

    samples: list[tuple[int, int, int]] = []
    coordinates = {
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    }
    for x, y in coordinates:
        r, g, b, _ = image.getpixel((x, y))
        samples.append((r, g, b))

    return Counter(samples).most_common(1)[0][0] if samples else None


def _remove_background_with_ben2(image: Image.Image) -> Image.Image:
    from .utils import remove_background_image

    return remove_background_image(image).convert("RGBA")


__all__ = [
    "PolishOptions",
    "add_one_pixel_outline",
    "center_on_canvas",
    "clean_background",
    "clean_background_with_ben2",
    "polish_image",
    "save_polished_copy",
    "trim_empty_padding",
]

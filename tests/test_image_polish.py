from typing import Any, cast

from PIL import Image

from spritesage.image_polish import (
    PolishOptions,
    add_one_pixel_outline,
    center_on_canvas,
    clean_background,
    clean_background_with_ben2,
    polish_image,
    save_polished_copy,
    trim_empty_padding,
)


def test_clean_background_thresholds_alpha_channel():
    image = Image.new("RGBA", (2, 1), cast(Any, (10, 20, 30, 255)))
    image.putpixel((0, 0), (10, 20, 30, 8))

    cleaned = clean_background(image, alpha_threshold=16)

    assert cleaned.getpixel((0, 0)) == (10, 20, 30, 0)
    assert cleaned.getpixel((1, 0)) == (10, 20, 30, 255)


def test_clean_background_removes_opaque_corner_color():
    image = Image.new("RGBA", (3, 3), cast(Any, (255, 255, 255, 255)))
    image.putpixel((1, 1), (20, 40, 60, 255))

    cleaned = clean_background(image, background_threshold=4)

    assert cleaned.getpixel((0, 0)) == (255, 255, 255, 0)
    assert cleaned.getpixel((1, 1)) == (20, 40, 60, 255)


def test_polish_clean_background_uses_ben2(monkeypatch):
    image = Image.new("RGBA", (3, 3), cast(Any, (255, 255, 255, 255)))
    image.putpixel((1, 1), (20, 40, 60, 255))
    ben2_output = Image.new("RGBA", (3, 3), cast(Any, (0, 0, 0, 0)))
    ben2_output.putpixel((1, 1), (20, 40, 60, 255))
    calls = []

    def fake_remove_background(input_image):
        calls.append(input_image.mode)
        return ben2_output

    monkeypatch.setattr(
        "spritesage.image_polish._remove_background_with_ben2",
        fake_remove_background,
    )

    polished = polish_image(
        image,
        PolishOptions(clean_background=True, trim_padding=False, center_on_canvas=False),
    )

    assert calls == ["RGB"]
    assert polished.getpixel((0, 0)) == (0, 0, 0, 0)
    assert polished.getpixel((1, 1)) == (20, 40, 60, 255)


def test_clean_background_with_ben2_falls_back_to_threshold(monkeypatch):
    image = Image.new("RGBA", (3, 3), cast(Any, (255, 255, 255, 255)))
    image.putpixel((1, 1), (20, 40, 60, 255))

    def fail_remove_background(_image):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "spritesage.image_polish._remove_background_with_ben2",
        fail_remove_background,
    )

    cleaned = clean_background_with_ben2(image, background_threshold=4)

    assert cleaned.getpixel((0, 0)) == (255, 255, 255, 0)
    assert cleaned.getpixel((1, 1)) == (20, 40, 60, 255)


def test_trim_empty_padding_crops_to_alpha_bounds():
    image = Image.new("RGBA", (5, 5), cast(Any, (0, 0, 0, 0)))
    image.putpixel((3, 2), (200, 10, 10, 255))

    trimmed = trim_empty_padding(image)

    assert trimmed.size == (1, 1)
    assert trimmed.getpixel((0, 0)) == (200, 10, 10, 255)


def test_center_on_canvas_keeps_original_dimensions():
    image = Image.new("RGBA", (1, 1), cast(Any, (20, 30, 40, 255)))

    centered = center_on_canvas(image, (5, 5))

    assert centered.size == (5, 5)
    assert centered.getpixel((2, 2)) == (20, 30, 40, 255)
    assert centered.getpixel((0, 0)) == (0, 0, 0, 0)


def test_add_one_pixel_outline_expands_canvas_and_preserves_source():
    image = Image.new("RGBA", (1, 1), cast(Any, (200, 40, 30, 255)))

    outlined = add_one_pixel_outline(image)

    assert outlined.size == (3, 3)
    assert outlined.getpixel((1, 1)) == (200, 40, 30, 255)
    assert outlined.getpixel((0, 1)) == (0, 0, 0, 255)


def test_polish_image_trims_outlines_and_recenters_on_original_canvas(monkeypatch):
    image = Image.new("RGBA", (5, 5), cast(Any, (255, 255, 255, 255)))
    image.putpixel((1, 1), (10, 50, 90, 255))

    monkeypatch.setattr(
        "spritesage.image_polish._remove_background_with_ben2",
        lambda input_image: clean_background(input_image, background_threshold=0),
    )

    polished = polish_image(
        image,
        PolishOptions(
            clean_background=True,
            trim_padding=True,
            center_on_canvas=True,
            add_outline=True,
            background_threshold=0,
        ),
    )

    assert polished.size == (5, 5)
    assert polished.getpixel((2, 2)) == (10, 50, 90, 255)
    assert polished.getpixel((1, 2)) == (0, 0, 0, 255)
    assert polished.getpixel((0, 0)) == (0, 0, 0, 0)


def test_save_polished_copy_uses_unique_suffix(tmp_path):
    source = tmp_path / "frame.png"
    existing = tmp_path / "frame_polished.png"
    source.write_bytes(b"source")
    existing.write_bytes(b"existing")
    image = Image.new("RGBA", (1, 1), cast(Any, (1, 2, 3, 255)))

    output = save_polished_copy(source, image)

    assert output == tmp_path / "frame_polished_2.png"
    assert output.exists()

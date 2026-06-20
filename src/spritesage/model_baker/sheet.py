from __future__ import annotations

from pathlib import Path

from PIL import Image


def make_contact_sheet(
    frames_by_view: dict[str, list[Path]],
    output_path: str | Path,
    cell_size: int,
) -> Path:
    """Create one grid sheet: rows are views, columns are animation frames."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    view_names = list(frames_by_view)
    columns = max((len(paths) for paths in frames_by_view.values()), default=1)
    rows = max(1, len(view_names))
    sheet = Image.new("RGBA", (columns * cell_size, rows * cell_size))

    for row, view_name in enumerate(view_names):
        for column, frame_path in enumerate(frames_by_view[view_name]):
            frame = Image.open(frame_path).convert("RGBA")
            if frame.size != (cell_size, cell_size):
                frame = frame.resize((cell_size, cell_size), Image.Resampling.NEAREST)
            sheet.alpha_composite(frame, (column * cell_size, row * cell_size))

    sheet.save(output_path)
    return output_path

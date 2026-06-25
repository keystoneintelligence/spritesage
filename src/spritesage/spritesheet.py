"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from pathlib import Path
from typing import Callable, List, Optional
from PIL import Image
from .sprite_file import SpriteFile
from .utils import remove_background_images

ProgressCallback = Callable[..., None]
ALPHA_EXTRACTION_BATCH_SIZE = 3


class SpriteSheetGenerator:
    """
    Generates a power-of-two sprite sheet PNG from a .sprite JSON definition.

    Attributes:
        data: Parsed JSON data from the .sprite file.
        width: Target width for each sprite frame.
        height: Target height for each sprite frame.
        animations: Dict mapping animation names to lists of frame file paths.
    """

    def __init__(self, sprite_file: SpriteFile):
        """
        Initializes the generator by loading and validating the .sprite JSON file.

        Args:
            sprite_file: Path to the .sprite JSON file.
        """
        self.sprite_file = sprite_file

        self.width = self.sprite_file.width
        self.height = self.sprite_file.height
        self.animations = self.sprite_file.animations

        if not isinstance(self.width, int) or not isinstance(self.height, int):
            raise ValueError("Sprite width and height must be integers.")

    @staticmethod
    def next_power_of_two(n: int) -> int:
        """
        Returns the smallest power of two greater than or equal to n.

        Args:
            n: Integer value.

        Returns:
            Next power of two >= n.
        """
        if n <= 0:
            return 1
        return 1 << (n - 1).bit_length()

    def get_all_frame_paths(self) -> List[str]:
        """
        Flattens the animations dict into a single list of frame file paths.

        Returns:
            List of file paths in the order defined by the animations.
        """
        frames: List[str] = []
        for animation_name in sorted(self.animations):
            frames.extend(self.sprite_file.get_animation_playback_frames(animation_name))
        return frames

    def determine_sheet_size(self, num_frames: int) -> int:
        """
        Determines the minimal square power-of-two sheet size to fit all frames.

        Args:
            num_frames: Total number of frames to place on the sheet.

        Returns:
            Integer side length (power of two) of the spritesheet.
        """
        # Start with the larger of width or height
        min_side = max(self.width, self.height)
        sheet_size = self.next_power_of_two(min_side)

        # Increase sheet_size until it can fit all frames in a grid
        while True:
            cols = sheet_size // self.width
            rows = sheet_size // self.height
            if cols * rows >= num_frames:
                return sheet_size
            sheet_size *= 2

    def create_spritesheet(
        self,
        output_path: Optional[str] = None,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        """
        Creates and saves the spritesheet PNG, arranging frames row-major.

        Args:
            output_path: Optional output PNG file path. If None, uses "<name>_spritesheet.png".

        Returns:
            Path to the saved spritesheet PNG.

        Raises:
            ValueError: If no frames are found in the sprite data.
        """
        frames = self.get_all_frame_paths()
        num_frames = len(frames)
        if num_frames == 0:
            raise ValueError("No frames found in sprite data.")

        sheet_size = self.determine_sheet_size(num_frames)
        cols = sheet_size // self.width

        self._report_progress(
            progress_callback,
            0,
            0,
            f"Checking transparency on {num_frames} frames",
        )
        frames_requiring_alpha = self._frames_requiring_alpha_extraction(frames)
        extraction_total = sum(frames_requiring_alpha)

        processed_frames: dict[int, Image.Image] = {}
        if extraction_total:
            self._report_progress(
                progress_callback,
                0,
                extraction_total,
                f"Preparing alpha extraction for {extraction_total} of {num_frames} frames",
            )
            processed_frames = self._extract_alpha_frames(
                frames=frames,
                frames_requiring_alpha=frames_requiring_alpha,
                progress_callback=progress_callback,
                extraction_total=extraction_total,
            )
        else:
            self._report_progress(
                progress_callback,
                0,
                0,
                f"All {num_frames} frames already have alpha; composing sprite sheet",
            )

        # Create a transparent RGBA sheet
        sheet = Image.new("RGBA", (sheet_size, sheet_size))

        # Paste each frame onto the sheet
        for idx, frame_path in enumerate(frames):
            if idx in processed_frames:
                img = processed_frames[idx]
            else:
                img = Image.open(frame_path).convert("RGBA")
                img = self._resize_frame(img)
            x = (idx % cols) * self.width
            y = (idx // cols) * self.height
            sheet.paste(img, (x, y), img)

        # Determine default output filename
        if not output_path:
            name = Path(self.sprite_file.name).stem
            output_path = f"{name}_spritesheet.png"

        sheet.save(output_path)
        self._report_progress(
            progress_callback,
            extraction_total,
            extraction_total,
            f"Saved sprite sheet with {num_frames} frames",
        )
        return output_path

    def _extract_alpha_frames(
        self,
        *,
        frames: List[str],
        frames_requiring_alpha: list[bool],
        progress_callback: ProgressCallback | None,
        extraction_total: int,
    ) -> dict[int, Image.Image]:
        processed_frames: dict[int, Image.Image] = {}
        batch_indices: list[int] = []
        batch_images: list[Image.Image] = []
        extraction_count = 0

        def flush_batch():
            nonlocal extraction_count
            if not batch_images:
                return
            batch_start = extraction_count + 1
            batch_end = extraction_count + len(batch_images)
            self._report_progress(
                progress_callback,
                extraction_count,
                extraction_total,
                f"Creating alpha channels for frames {batch_start}-{batch_end} of {extraction_total}",
            )
            outputs = remove_background_images(batch_images)
            for frame_index, output in zip(batch_indices, outputs):
                processed_frames[frame_index] = output
            extraction_count += len(outputs)
            self._report_progress(
                progress_callback,
                extraction_count,
                extraction_total,
                f"Created alpha channels for {extraction_count} of {extraction_total} frames",
            )
            batch_indices.clear()
            batch_images.clear()

        for idx, frame_path in enumerate(frames):
            if not frames_requiring_alpha[idx]:
                continue
            image = Image.open(frame_path).convert("RGBA")
            batch_indices.append(idx)
            batch_images.append(self._resize_frame(image))
            if len(batch_images) >= ALPHA_EXTRACTION_BATCH_SIZE:
                flush_batch()
        flush_batch()
        return processed_frames

    def _resize_frame(self, image: Image.Image) -> Image.Image:
        if image.size == (self.width, self.height):
            return image
        return image.resize((self.width, self.height), Image.Resampling.LANCZOS)

    def _frames_requiring_alpha_extraction(self, frames: List[str]) -> list[bool]:
        needs_alpha = []
        for frame_path in frames:
            with Image.open(frame_path) as image:
                needs_alpha.append(not self._has_meaningful_alpha(image))
        return needs_alpha

    @staticmethod
    def _has_meaningful_alpha(image: Image.Image) -> bool:
        if "A" not in image.getbands():
            return False

        alpha = image.getchannel("A")
        min_alpha, max_alpha = alpha.getextrema()
        if max_alpha == 0:
            return True
        if min_alpha == 255:
            return False

        histogram = alpha.histogram()
        transparent_pixels = sum(histogram[:5])
        min_transparent_pixels = max(1, int(image.width * image.height * 0.005))
        return transparent_pixels >= min_transparent_pixels

    @staticmethod
    def _report_progress(
        progress_callback: ProgressCallback | None,
        current: int,
        total: int,
        detail: str,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(current, total, detail)
        except TypeError:
            progress_callback(current, total)

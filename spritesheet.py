"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from pathlib import Path
from typing import List, Optional
from PIL import Image
from sprite_file import SpriteFile
from utils import remove_background


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
        for animation in self.animations.values():
            frames.extend(animation.frames)
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

    def create_spritesheet(self, output_path: Optional[str] = None) -> str:
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

        # Create a transparent RGBA sheet
        sheet = Image.new('RGBA', (sheet_size, sheet_size), (0, 0, 0, 0))

        # Paste each frame onto the sheet
        for idx, frame_path in enumerate(frames):
            img = Image.open(frame_path).convert('RGBA')
            img = img.resize((self.width, self.height), Image.ANTIALIAS)
            x = (idx % cols) * self.width
            y = (idx // cols) * self.height
            sheet.paste(img, (x, y), img)

        # Determine default output filename
        if not output_path:
            name = Path(self.sprite_file.name).stem
            output_path = f"{name}_spritesheet.png"

        sheet.save(output_path)
        remove_background(output_path, output_path)
        return output_path

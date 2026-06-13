"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import json
from typing import List
from datetime import datetime
from dataclasses import dataclass


@dataclass
class SageFile:
    project_name: str
    version: str
    created_at: str
    project_description: str
    keywords: str
    camera: str
    reference_images: List[str]
    last_saved: str
    filepath: str

    @classmethod
    def from_dict(cls, data: dict, filepath: str) -> "SageFile":
        instance = cls(
            project_name=data.get("Project Name", ""),
            version=data.get("version", ""),
            created_at=data.get("createdAt", ""),
            project_description=data.get("Project Description", ""),
            keywords=data.get("Keywords", ""),
            camera=data.get("Camera", ""),
            reference_images=[],
            last_saved=data.get("lastSaved", ""),
            filepath=filepath
        )
        instance.reference_images = [os.path.join(instance.directory, x) for x in data.get("Reference Images", [])]
        return instance

    @classmethod
    def from_json(cls, filepath: str) -> "SageFile":
        with open(filepath) as f:
            json_data = json.load(f)
        return cls.from_dict(data=json_data, filepath=filepath)

    def to_dict(self) -> dict:
        return {
            "Project Name": self.project_name,
            "version": self.version,
            "createdAt": self.created_at,
            "Project Description": self.project_description,
            "Keywords": self.keywords,
            "Camera": self.camera,
            "Reference Images": [os.path.relpath(x, self.directory) for x in self.reference_images],
            "lastSaved": self.last_saved
        }

    @property
    def directory(self) -> str:
        """
        Returns the directory path containing the file.

        Example:
            If self.filepath is "/path/to/your/project/file.sage",
            this property will return "/path/to/your/project".
        """
        # os.path.dirname reliably gets the directory part of a path,
        # handling different OS separators correctly.
        return os.path.dirname(self.filepath)

    def update_last_saved(self):
        self.last_saved = datetime.now().isoformat(timespec="seconds")

    def save(self):
        self.update_last_saved()
        with open(self.filepath, "w") as f:
            # Serialize current state to JSON
            json.dump(self.to_dict(), f)

    def reference_image_abs_paths(self, exclude_index: int | None = None) -> list[str]:
        """Returns a list of absolute image paths from the widgets, optionally excluding one."""
        abs_paths = []
        image_loaders = self.reference_images
        for i, rel_path in enumerate(image_loaders):
            if i == exclude_index:
                continue # Skip excluded index
            if rel_path:
                try:
                    abs_path = os.path.abspath(os.path.join(self.directory, rel_path))
                    if os.path.isfile(abs_path): # Only add valid, existing files
                        abs_paths.append(abs_path)
                    else:
                        print(f"Warning: Image path '{rel_path}' (index {i}) does not resolve to a valid file. Skipping for AI context.")
                except Exception as e:
                    print(f"Error resolving absolute path for '{rel_path}': {e}")
        return abs_paths

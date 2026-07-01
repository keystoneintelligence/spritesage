"""
SPDX-License-Identifier: GPL-3.0-only
Copyright (C) 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

# pyright: strict

import os
from typing import Any, cast

from .config import MAX_RECENT_PROJECTS, RECENT_PROJECTS_KEY, SAGE_FILE_EXTENSION

RecentProject = dict[str, str]


def make_recent_project(
    project_dir: str, sage_file: str, project_name: str | None = None
) -> RecentProject:
    """Return the normalized settings payload for one recent project."""
    sage_path = os.path.abspath(sage_file)
    directory = os.path.abspath(project_dir)
    name = (
        project_name
        or os.path.splitext(os.path.basename(sage_path))[0]
        or os.path.basename(directory)
    )
    return {"name": name, "path": sage_path, "project_dir": directory}


def recent_project_label(project: RecentProject) -> str:
    """Return a short user-facing label for menus and lists."""
    return project.get("name") or os.path.splitext(os.path.basename(project.get("path", "")))[0]


def _dedupe_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def normalize_recent_projects(
    value: Any, max_count: int = MAX_RECENT_PROJECTS
) -> list[RecentProject]:
    """Normalize saved recent-project settings and drop unusable records."""
    if not isinstance(value, list):
        return []

    normalized: list[RecentProject] = []
    seen: set[str] = set()
    items = cast(list[Any], value)
    for item in items:
        if isinstance(item, str):
            sage_path = item
            project_dir = os.path.dirname(item)
            project_name = None
        elif isinstance(item, dict):
            item_data = cast(dict[str, object], item)
            sage_path = str(item_data.get("path", "")).strip()
            project_dir = str(item_data.get("project_dir", "")).strip() or os.path.dirname(
                sage_path
            )
            project_name = str(item_data.get("name", "")).strip() or None
        else:
            continue

        if not sage_path or not sage_path.lower().endswith(SAGE_FILE_EXTENSION):
            continue

        entry = make_recent_project(project_dir, sage_path, project_name)
        key = _dedupe_key(entry["path"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(entry)
        if len(normalized) >= max_count:
            break
    return normalized


def recent_projects_from_settings(settings: dict[str, Any]) -> list[RecentProject]:
    return normalize_recent_projects(settings.get(RECENT_PROJECTS_KEY, []))


def add_recent_project(
    current: list[RecentProject],
    project_dir: str,
    sage_file: str,
    project_name: str | None = None,
    max_count: int = MAX_RECENT_PROJECTS,
) -> list[RecentProject]:
    """Return recents with the supplied project moved to the front."""
    new_entry = make_recent_project(project_dir, sage_file, project_name)
    new_key = _dedupe_key(new_entry["path"])
    remaining = [
        project
        for project in normalize_recent_projects(current, max_count=max_count)
        if _dedupe_key(project["path"]) != new_key
    ]
    return [new_entry, *remaining][:max_count]

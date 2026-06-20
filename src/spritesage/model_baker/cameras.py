from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ViewSpec:
    name: str
    azimuth: float
    elevation: float


VIEW_SETS: dict[str, tuple[ViewSpec, ...]] = {
    "front3": (
        ViewSpec("front", 0.0, 0.0),
        ViewSpec("left", -90.0, 0.0),
        ViewSpec("right", 90.0, 0.0),
    ),
    "side2": (
        ViewSpec("left", -90.0, 0.0),
        ViewSpec("right", 90.0, 0.0),
    ),
    "iso4": (
        ViewSpec("front_right", 45.0, 35.264),
        ViewSpec("back_right", 135.0, 35.264),
        ViewSpec("back_left", 225.0, 35.264),
        ViewSpec("front_left", 315.0, 35.264),
    ),
    "iso8": (
        ViewSpec("front", 0.0, 35.264),
        ViewSpec("front_right", 45.0, 35.264),
        ViewSpec("right", 90.0, 35.264),
        ViewSpec("back_right", 135.0, 35.264),
        ViewSpec("back", 180.0, 35.264),
        ViewSpec("back_left", 225.0, 35.264),
        ViewSpec("left", 270.0, 35.264),
        ViewSpec("front_left", 315.0, 35.264),
    ),
    "top": (ViewSpec("top", 0.0, 89.0),),
}


def resolve_view_set(name: str) -> tuple[ViewSpec, ...]:
    try:
        return VIEW_SETS[name]
    except KeyError as exc:
        known = ", ".join(sorted(VIEW_SETS))
        raise ValueError(f"Unknown view set '{name}'. Known view sets: {known}") from exc


def bounds_center_radius(bounds: Iterable[float]) -> tuple[np.ndarray, float]:
    xmin, xmax, ymin, ymax, zmin, zmax = [float(value) for value in bounds]
    center = np.array(
        [(xmin + xmax) * 0.5, (ymin + ymax) * 0.5, (zmin + zmax) * 0.5],
        dtype=float,
    )
    extents = np.array([xmax - xmin, ymax - ymin, zmax - zmin], dtype=float)
    radius = float(np.linalg.norm(extents) * 0.5)
    return center, max(radius, 1e-6)


def camera_direction(view: ViewSpec) -> np.ndarray:
    azimuth = math.radians(view.azimuth)
    elevation = math.radians(view.elevation)
    horizontal = math.cos(elevation)
    return np.array(
        [
            horizontal * math.sin(azimuth),
            math.sin(elevation),
            horizontal * math.cos(azimuth),
        ],
        dtype=float,
    )


def apply_camera(renderer, bounds: Iterable[float], view: ViewSpec, zoom: float = 1.0) -> None:
    """Apply a fixed orthographic camera to a VTK renderer."""
    if zoom <= 0:
        raise ValueError("zoom must be greater than zero")

    center, radius = bounds_center_radius(bounds)
    direction = camera_direction(view)
    distance = max(radius * 4.0, 1e-3)
    position = center + direction * distance
    view_up = np.array([0.0, 1.0, 0.0], dtype=float)
    if abs(float(np.dot(direction, view_up))) > 0.95:
        view_up = np.array([0.0, 0.0, -1.0], dtype=float)

    camera = renderer.GetActiveCamera()
    camera.SetPosition(float(position[0]), float(position[1]), float(position[2]))
    camera.SetFocalPoint(float(center[0]), float(center[1]), float(center[2]))
    camera.SetViewUp(float(view_up[0]), float(view_up[1]), float(view_up[2]))
    camera.SetParallelProjection(True)
    camera.SetParallelScale((radius * 1.15) / zoom)
    renderer.ResetCameraClippingRange()

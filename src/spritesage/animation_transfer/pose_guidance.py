"""Screen-space facts from an animated humanoid rig for local edit prompts."""

from __future__ import annotations

import re

import numpy as np

from spritesage.model_baker.cameras import bounds_center_radius, camera_direction, resolve_view_set
from spritesage.model_baker.skinned_gltf import SkinnedGltf


def _joint(points: dict[str, tuple[float, float]], *aliases: str):
    normalized = {re.sub(r"[^a-z0-9]", "", name.lower()): value for name, value in points.items()}
    for alias in aliases:
        for name, value in normalized.items():
            if name == alias or name.endswith(alias):
                return value
    return None


def rig_constraints(points: dict[str, tuple[float, float]], size: int) -> tuple[str, ...]:
    """Keep constraints conservative when a rig has missing or unfamiliar joints."""
    head = _joint(points, "head")
    face = _joint(points, "headfront", "facefront", "nose")
    left_foot = _joint(points, "leftfoot", "footl")
    right_foot = _joint(points, "rightfoot", "footr")
    left_hand = _joint(points, "lefthand", "handl")
    right_hand = _joint(points, "righthand", "handr")
    facts = []
    if head and face and abs(face[0] - head[0]) >= size * 0.025:
        facing = "left" if face[0] < head[0] else "right"
        facts.append(f"The rig verifies that the face points toward screen {facing}.")
    if left_foot and right_foot:
        screen_left, screen_right = sorted((left_foot, right_foot), key=lambda p: p[0])
        delta = screen_left[1] - screen_right[1]
        if delta > size * 0.025:
            facts.append("The screen-right boot is higher than the screen-left boot.")
        elif delta < -size * 0.025:
            facts.append("The screen-left boot is higher than the screen-right boot.")
        else:
            facts.append("Both boots are at approximately the same screen height.")
        facts.append(
            "The boot centers are approximately at "
            f"{round(screen_left[0] / size * 100)}% and "
            f"{round(screen_right[0] / size * 100)}% of the canvas width from the left."
        )
    if left_hand and right_hand:
        hands = sorted((left_hand, right_hand), key=lambda p: p[0])
        facts.append(
            "The hand centers are approximately at "
            f"{round(hands[0][0] / size * 100)}% and "
            f"{round(hands[1][0] / size * 100)}% of the canvas width from the left."
        )
    if facts:
        facts.append(
            "These rig positions take precedence if the pose image is ambiguous. "
            "Do not widen the stride, extend an arm, or change foot contact beyond <image1>."
        )
    return tuple(facts)


class RigPoseGuide:
    """Use the same sampled motion and locked camera bounds as the pose renderer."""

    def __init__(self, model_path, pose_manifest: dict, view_set: str, size: int, zoom: float):
        self.model = SkinnedGltf(model_path)
        self.size = size
        self.zoom = zoom
        self.views = {view.name: view for view in resolve_view_set(view_set)}
        self.records = {record["name"]: record for record in pose_manifest["animations"]}
        samples = [
            self.model.deformed_points(record["index"], float(time_value))
            for record in pose_manifest["animations"]
            for time_value in record["times"]
        ]
        positions = np.concatenate(samples)
        bounds = (
            float(positions[:, 0].min()),
            float(positions[:, 0].max()),
            float(positions[:, 1].min()),
            float(positions[:, 1].max()),
            float(positions[:, 2].min()),
            float(positions[:, 2].max()),
        )
        self.center, self.radius = bounds_center_radius(bounds)

    def constraints(self, animation: str, direction: str, index: int) -> tuple[str, ...]:
        record = self.records[animation]
        joints = self.model.joint_world_positions(record["index"], float(record["times"][index]))
        view = self.views[direction]
        forward = -camera_direction(view)
        up = np.array([0.0, 1.0, 0.0])
        if abs(float(np.dot(forward, up))) > 0.95:
            up = np.array([0.0, 0.0, -1.0])
        right = np.cross(forward, up)
        right /= np.linalg.norm(right)
        scale = self.radius * 1.15 / self.zoom
        projected = {
            name: (
                self.size / 2
                + float(np.dot(position - self.center, right)) / (2 * scale) * self.size,
                self.size / 2 - float(np.dot(position - self.center, up)) / (2 * scale) * self.size,
            )
            for name, position in joints.items()
        }
        return rig_constraints(projected, self.size)

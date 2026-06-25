from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from pygltflib import GLTF2
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals

_COMPONENT_DTYPES = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}

_TYPE_SHAPES = {
    "SCALAR": (),
    "VEC2": (2,),
    "VEC3": (3,),
    "VEC4": (4,),
    "MAT4": (4, 4),
}


@dataclass
class NodePose:
    translation: np.ndarray
    rotation: np.ndarray
    scale: np.ndarray


class SkinnedGltf:
    """Minimal CPU skinner for the prototype bandit-style GLB assets."""

    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        gltf = GLTF2().load(str(self.model_path))
        if gltf is None:
            raise ValueError(f"Could not load GLB model: {self.model_path}")
        self.gltf: GLTF2 = gltf
        blob = self.gltf.binary_blob()
        if blob is None:
            raise ValueError("Only binary GLB assets are supported by this prototype skinner")
        self._blob = blob

        self.mesh_node_index = self._find_mesh_node()
        self.mesh_node = self.gltf.nodes[self.mesh_node_index]
        if self.mesh_node.mesh is None or self.mesh_node.skin is None:
            raise ValueError("Expected a skinned mesh node")

        mesh = self.gltf.meshes[self.mesh_node.mesh]
        if len(mesh.primitives or []) != 1:
            raise ValueError("Only single-primitive skinned meshes are supported")
        primitive = mesh.primitives[0]
        attributes = primitive.attributes

        self.base_positions = self.accessor_array(attributes.POSITION).astype(np.float32)
        self.uvs = self.accessor_array(attributes.TEXCOORD_0).astype(np.float32)
        self.joints = self.accessor_array(attributes.JOINTS_0).astype(np.int64)
        self.weights = self.accessor_array(attributes.WEIGHTS_0).astype(np.float32)
        self.indices = self.accessor_array(primitive.indices).astype(np.int64)

        skin = self.gltf.skins[self.mesh_node.skin]
        self.joint_nodes = list(skin.joints or [])
        self.inverse_bind_matrices = self.accessor_array(skin.inverseBindMatrices).astype(
            np.float32
        )

        self.parents = self._build_parent_table()
        self.base_poses = [self._node_pose(node) for node in self.gltf.nodes]

    @property
    def texture_coordinates(self) -> np.ndarray:
        return self.uvs

    def accessor_array(self, accessor_index: int | None) -> np.ndarray:
        if accessor_index is None:
            raise ValueError("Missing required accessor")

        accessor = self.gltf.accessors[accessor_index]
        if accessor.bufferView is None:
            raise ValueError(f"Accessor {accessor_index} has no buffer view")
        buffer_view = self.gltf.bufferViews[accessor.bufferView]
        dtype = np.dtype(_COMPONENT_DTYPES[accessor.componentType])
        shape = _TYPE_SHAPES[accessor.type]
        item_components = int(np.prod(shape)) if shape else 1
        item_bytes = dtype.itemsize * item_components
        stride = buffer_view.byteStride or item_bytes
        offset = (buffer_view.byteOffset or 0) + (accessor.byteOffset or 0)

        data = np.frombuffer(self._blob, dtype=np.uint8)
        if stride == item_bytes:
            raw = np.frombuffer(
                self._blob,
                dtype=dtype,
                count=accessor.count * item_components,
                offset=offset,
            )
            array = raw.reshape((accessor.count, *shape)) if shape else raw
        else:
            rows = []
            for index in range(accessor.count):
                start = offset + index * stride
                end = start + item_bytes
                row = np.frombuffer(data[start:end].tobytes(), dtype=dtype, count=item_components)
                rows.append(row)
            raw = np.vstack(rows)
            array = raw.reshape((accessor.count, *shape)) if shape else raw[:, 0]

        if accessor.type == "MAT4":
            return np.swapaxes(array, 1, 2)
        return array

    def deformed_points(self, animation_index: int, time_value: float) -> np.ndarray:
        poses = [
            NodePose(p.translation.copy(), p.rotation.copy(), p.scale.copy())
            for p in self.base_poses
        ]
        if animation_index >= 0:
            self._apply_animation(animation_index, time_value, poses)

        globals_by_node = self._global_matrices(poses)
        mesh_global = globals_by_node[self.mesh_node_index]
        mesh_global_inv = np.linalg.inv(mesh_global)
        joint_matrices = np.stack(
            [
                mesh_global_inv
                @ globals_by_node[node_index]
                @ self.inverse_bind_matrices[joint_index]
                for joint_index, node_index in enumerate(self.joint_nodes)
            ],
            axis=0,
        )

        local_positions = self._skin_points(joint_matrices)
        homogeneous = np.c_[local_positions, np.ones(len(local_positions), dtype=np.float32)]
        world = (mesh_global @ homogeneous.T).T[:, :3]
        return world.astype(np.float32)

    def to_polydata(self, points: np.ndarray) -> vtkPolyData:
        vtk_points = vtkPoints()
        vtk_points.SetData(numpy_to_vtk(np.ascontiguousarray(points), deep=True))

        triangles = vtkCellArray()
        offsets = np.arange(0, len(self.indices) + 1, 3, dtype=np.int64)
        triangles.SetData(
            numpy_to_vtkIdTypeArray(offsets, deep=True),
            numpy_to_vtkIdTypeArray(np.ascontiguousarray(self.indices), deep=True),
        )

        mesh = vtkPolyData()
        mesh.SetPoints(vtk_points)
        mesh.SetPolys(triangles)

        texture_coordinates = numpy_to_vtk(np.ascontiguousarray(self.uvs), deep=True)
        texture_coordinates.SetName("TextureCoordinates")
        texture_coordinates.SetNumberOfComponents(2)
        mesh.GetPointData().SetTCoords(texture_coordinates)

        normals = vtkPolyDataNormals()
        normals.SetInputData(mesh)
        normals.SetConsistency(True)
        normals.AutoOrientNormalsOff()
        normals.SplittingOff()
        normals.Update()

        output = vtkPolyData()
        output.ShallowCopy(normals.GetOutput())
        return output

    def _skin_points(self, joint_matrices: np.ndarray) -> np.ndarray:
        homogeneous = np.c_[
            self.base_positions,
            np.ones(len(self.base_positions), dtype=np.float32),
        ]
        out = np.zeros((len(self.base_positions), 4), dtype=np.float32)

        weight_sums = self.weights.sum(axis=1)
        safe_weights = self.weights.copy()
        needs_normalization = weight_sums > 0
        safe_weights[needs_normalization] /= weight_sums[needs_normalization, None]

        for influence in range(safe_weights.shape[1]):
            joint_indices = self.joints[:, influence]
            weights = safe_weights[:, influence]
            transformed = np.einsum("nij,nj->ni", joint_matrices[joint_indices], homogeneous)
            out += transformed * weights[:, None]
        return out[:, :3]

    def _apply_animation(
        self,
        animation_index: int,
        time_value: float,
        poses: list[NodePose],
    ) -> None:
        animation = self.gltf.animations[animation_index]
        for channel in animation.channels or []:
            if channel.sampler is None:
                raise ValueError(f"Animation channel in '{animation.name}' has no sampler")
            sampler = animation.samplers[channel.sampler]
            times = self.accessor_array(sampler.input).astype(np.float32)
            values = self.accessor_array(sampler.output).astype(np.float32)
            value = _sample_values(
                times, values, float(time_value), sampler.interpolation or "LINEAR"
            )

            if channel.target.node is None:
                raise ValueError(f"Animation channel in '{animation.name}' has no target node")
            pose = poses[channel.target.node]
            if channel.target.path == "translation":
                pose.translation = value.astype(np.float32)
            elif channel.target.path == "rotation":
                pose.rotation = _normalize_quaternion(value.astype(np.float32))
            elif channel.target.path == "scale":
                pose.scale = value.astype(np.float32)

    def _global_matrices(self, poses: list[NodePose]) -> list[np.ndarray]:
        globals_by_node: list[np.ndarray | None] = [None for _ in self.gltf.nodes]

        def compute(node_index: int) -> np.ndarray:
            cached = globals_by_node[node_index]
            if cached is not None:
                return cached
            local = _trs_matrix(poses[node_index])
            parent = self.parents[node_index]
            matrix = local if parent is None else compute(parent) @ local
            globals_by_node[node_index] = matrix
            return matrix

        return [compute(index) for index in range(len(self.gltf.nodes))]

    def _find_mesh_node(self) -> int:
        for index, node in enumerate(self.gltf.nodes):
            if node.mesh is not None and node.skin is not None:
                return index
        raise ValueError("No skinned mesh node found")

    def _build_parent_table(self) -> list[int | None]:
        parents: list[int | None] = [None for _ in self.gltf.nodes]
        for parent_index, node in enumerate(self.gltf.nodes):
            for child_index in node.children or []:
                parents[child_index] = parent_index
        return parents

    def _node_pose(self, node) -> NodePose:
        if node.matrix is not None:
            raise ValueError("Prototype skinner does not support node.matrix transforms yet")
        return NodePose(
            translation=np.array(node.translation or [0.0, 0.0, 0.0], dtype=np.float32),
            rotation=_normalize_quaternion(
                np.array(node.rotation or [0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            ),
            scale=np.array(node.scale or [1.0, 1.0, 1.0], dtype=np.float32),
        )


def _sample_values(
    times: np.ndarray,
    values: np.ndarray,
    time_value: float,
    interpolation: str,
) -> np.ndarray:
    if len(times) == 0:
        raise ValueError("Animation sampler has no keyframes")
    if time_value <= float(times[0]):
        return values[0]
    if time_value >= float(times[-1]):
        return values[-1]

    upper = int(np.searchsorted(times, time_value, side="right"))
    lower = upper - 1
    t0 = float(times[lower])
    t1 = float(times[upper])
    amount = 0.0 if math.isclose(t0, t1) else (time_value - t0) / (t1 - t0)

    if interpolation == "STEP":
        return values[lower]
    if interpolation != "LINEAR":
        raise ValueError(f"Unsupported animation interpolation: {interpolation}")

    if values.shape[1:] == (4,):
        return _slerp(values[lower], values[upper], amount)
    return values[lower] * (1.0 - amount) + values[upper] * amount


def _trs_matrix(pose: NodePose) -> np.ndarray:
    translation = np.eye(4, dtype=np.float32)
    translation[:3, 3] = pose.translation

    rotation = np.eye(4, dtype=np.float32)
    rotation[:3, :3] = _quaternion_matrix(pose.rotation)

    scale = np.diag([pose.scale[0], pose.scale[1], pose.scale[2], 1.0]).astype(np.float32)
    return translation @ rotation @ scale


def _quaternion_matrix(quaternion: Iterable[float]) -> np.ndarray:
    x, y, z, w = _normalize_quaternion(np.array(quaternion, dtype=np.float32))
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=np.float32,
    )


def _normalize_quaternion(quaternion: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(quaternion))
    if norm == 0:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    return (quaternion / norm).astype(np.float32)


def _slerp(q0: np.ndarray, q1: np.ndarray, amount: float) -> np.ndarray:
    left = _normalize_quaternion(q0)
    right = _normalize_quaternion(q1)
    dot = float(np.dot(left, right))
    if dot < 0.0:
        right = -right
        dot = -dot

    if dot > 0.9995:
        return _normalize_quaternion(left + amount * (right - left))

    theta_0 = math.acos(np.clip(dot, -1.0, 1.0))
    theta = theta_0 * amount
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)
    s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    return _normalize_quaternion((s0 * left) + (s1 * right))

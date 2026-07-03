from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from PIL import Image
import pygltflib
from vtkmodules.util.numpy_support import numpy_to_vtk
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.vtkRenderingCore import vtkTexture


def extract_texture_from_gltf_or_glb(path: str | Path) -> vtkTexture | None:
    """Extract the primary base color texture from a GLB/GLTF as a VTK texture."""
    path = Path(path)
    try:
        if path.suffix.lower() not in {".glb", ".gltf"}:
            return None
        gltf = pygltflib.GLTF2().load(str(path))
        if gltf is None:
            return None
        if not gltf.images:
            return None

        image_def = gltf.images[_base_color_image_index(gltf)]
        texture_image = _load_gltf_image(gltf, path, image_def)
        if texture_image is None:
            return None

        pixels = np.ascontiguousarray(np.array(texture_image.convert("RGBA"), dtype=np.uint8))
        height, width, channels = pixels.shape

        image_data = vtkImageData()
        image_data.SetDimensions(width, height, 1)
        vtk_pixels = numpy_to_vtk(pixels.reshape((-1, channels)), deep=True)
        vtk_pixels.SetNumberOfComponents(channels)
        image_data.GetPointData().SetScalars(vtk_pixels)

        texture = vtkTexture()
        texture.SetInputData(image_data)
        texture.InterpolateOn()
        texture.RepeatOff()
        texture.EdgeClampOn()
        texture.MipmapOff()
        return texture
    except Exception as exc:
        logging.warning("Could not extract texture from %s: %s", path, exc)
        return None


def _base_color_image_index(gltf: pygltflib.GLTF2) -> int:
    for material in gltf.materials or []:
        pbr = material.pbrMetallicRoughness
        texture_info = getattr(pbr, "baseColorTexture", None) if pbr else None
        texture_index = getattr(texture_info, "index", None)
        if texture_index is None:
            continue
        if texture_index < 0 or texture_index >= len(gltf.textures or []):
            continue
        source_index = gltf.textures[texture_index].source
        if source_index is not None and 0 <= source_index < len(gltf.images or []):
            return source_index
    return 0


def _load_gltf_image(
    gltf: pygltflib.GLTF2,
    model_path: Path,
    image_def,
) -> Image.Image | None:
    if image_def.bufferView is not None:
        view = gltf.bufferViews[image_def.bufferView]
        if view.buffer is None:
            return None
        data = _buffer_bytes(gltf, view.buffer)
        if data is None:
            return None
        offset = view.byteOffset or 0
        image_data = data[offset : offset + view.byteLength]
        return Image.open(BytesIO(image_data))

    if not image_def.uri:
        return None
    if image_def.uri.startswith("data:"):
        return Image.open(BytesIO(gltf.get_data_from_buffer_uri(image_def.uri)))

    image_path = model_path.parent / unquote(urlparse(image_def.uri).path)
    if not os.path.exists(image_path):
        return None
    return Image.open(image_path)


def _buffer_bytes(gltf: pygltflib.GLTF2, buffer_index: int) -> bytes | None:
    buffer = gltf.buffers[buffer_index]
    if buffer.uri:
        return gltf.get_data_from_buffer_uri(buffer.uri)
    return gltf.binary_blob()

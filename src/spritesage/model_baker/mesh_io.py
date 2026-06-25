from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
import pygltflib
from vtkmodules.util.numpy_support import numpy_to_vtk
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.vtkRenderingCore import vtkTexture


def extract_texture_from_gltf_or_glb(path: str | Path) -> vtkTexture | None:
    """Extract the first embedded or referenced GLB/GLTF texture as a VTK texture."""
    path = str(path)
    try:
        if not path.lower().endswith((".glb", ".gltf")):
            return None
        gltf = pygltflib.GLTF2().load(path)
        if gltf is None:
            return None
        if not gltf.images:
            return None

        image_def = gltf.images[0]
        if image_def.bufferView is None:
            if not image_def.uri:
                return None
            image_path = os.path.join(os.path.dirname(path), image_def.uri)
            if not os.path.exists(image_path):
                return None
            texture_image = Image.open(image_path)
        else:
            view = gltf.bufferViews[image_def.bufferView]
            if view.buffer is None:
                return None
            data = gltf.get_data_from_buffer_uri(gltf.buffers[view.buffer].uri)
            if data is None:
                return None
            offset = view.byteOffset or 0
            image_data = data[offset : offset + view.byteLength]
            texture_image = Image.open(BytesIO(image_data))

        flipped = texture_image.convert("RGBA").transpose(Image.FLIP_TOP_BOTTOM)
        pixels = np.ascontiguousarray(np.array(flipped, dtype=np.uint8))
        height, width, channels = pixels.shape

        image_data = vtkImageData()
        image_data.SetDimensions(width, height, 1)
        vtk_pixels = numpy_to_vtk(pixels.reshape((-1, channels)), deep=True)
        vtk_pixels.SetNumberOfComponents(channels)
        image_data.GetPointData().SetScalars(vtk_pixels)

        texture = vtkTexture()
        texture.SetInputData(image_data)
        texture.InterpolateOn()
        return texture
    except Exception as exc:
        logging.warning("Could not extract texture from %s: %s", path, exc)
        return None

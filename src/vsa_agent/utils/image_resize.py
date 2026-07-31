"""Image resizing helpers for bounded multimodal model inputs."""

from __future__ import annotations

import math
from typing import Any


def dimensions_within_pixel_budget(width: int, height: int, max_pixels: int) -> tuple[int, int]:
    """Return aspect-preserving dimensions whose area does not exceed the budget."""
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if max_pixels <= 0:
        raise ValueError("max_pixels must be positive")
    if width * height <= max_pixels:
        return width, height

    scale = math.sqrt(max_pixels / (width * height))
    resized_width = max(1, math.floor(width * scale))
    resized_height = max(1, math.floor(height * scale))
    while resized_width * resized_height > max_pixels:
        if resized_width >= resized_height:
            resized_width -= 1
        else:
            resized_height -= 1
    return resized_width, resized_height


def resize_frame_to_pixel_budget(frame: Any, max_pixels: int, *, cv2_module: Any) -> Any:
    """Resize an OpenCV frame only when its pixel area exceeds the hard limit."""
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        return frame
    height, width = int(shape[0]), int(shape[1])
    resized_width, resized_height = dimensions_within_pixel_budget(width, height, max_pixels)
    if (resized_width, resized_height) == (width, height):
        return frame
    return cv2_module.resize(
        frame,
        (resized_width, resized_height),
        interpolation=cv2_module.INTER_AREA,
    )

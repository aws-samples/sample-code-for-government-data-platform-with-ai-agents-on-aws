"""Draws an index or change grid as a PNG map overlay on one fixed diverging colour scale, and builds the map_overlay event with its legend and the scenes it came from."""
import base64
import struct
import zlib
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# A change saturates at ±0.3, an index at ±1
CHANGE_CLAMP = 0.3
INDEX_CLAMP = 1.0

_FALL = np.array([140, 81, 10], dtype="float64")
_NONE = np.array([245, 245, 245], dtype="float64")
_RISE = np.array([1, 102, 94], dtype="float64")
LEGEND_STOPS = (-1.0, -0.5, 0.0, 0.5, 1.0)

NOTE = "A spectral index is a measurement of reflected light, not a land-use classification."


def colours(values: Any, clamp: float) -> np.ndarray:
    """RGBA uint8 for each value: brown for a fall, near white for none, green for a rise; NaN is transparent."""
    grid = np.atleast_2d(np.asarray(values, dtype="float64"))
    finite = np.isfinite(grid)
    t = np.clip(np.where(finite, grid, 0.0) / clamp, -1.0, 1.0)[..., None]
    rgb = np.where(t >= 0, _NONE + (_RISE - _NONE) * t, _NONE + (_FALL - _NONE) * -t)
    alpha = np.where(finite, 255, 0)[..., None]
    return np.concatenate([np.round(rgb), alpha], axis=-1).astype("uint8")


def png_base64(values: Any, clamp: float) -> Optional[str]:
    """The grid as a base64 PNG, one pixel per cell, or None for an empty grid."""
    rgba = colours(values, clamp)
    height, width = rgba.shape[:2]
    if not height or not width:
        return None

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row.tobytes() for row in rgba)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def legend_swatches(clamp: float) -> List[Dict[str, Any]]:
    """The scale as [{"value", "rgba"}], low first, taken from the same ramp as the pixels."""
    values = [round(stop * clamp, 4) for stop in LEGEND_STOPS]
    return [{"value": v, "rgba": [int(c) for c in colours([[v]], clamp)[0, 0]]} for v in values]


def overlay_event(aoi_bbox: Sequence[float], index: str, grid: Any, after: Dict[str, Any], before: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The map_overlay event value for an index grid, or a change grid when before is given; None when there is nothing to draw."""
    change = before is not None
    image = png_base64(grid, CHANGE_CLAMP if change else INDEX_CLAMP) if grid is not None else None
    if not image:
        return None
    west, south, east, north = aoi_bbox
    return {
        "bounds": [[south, west], [north, east]],
        "image_data": image,
        "legend": {
            "kind": "change" if change else "index",
            "index": index,
            "swatches": legend_swatches(CHANGE_CLAMP if change else INDEX_CLAMP),
            "meaning": "green where the index rose, brown where it fell" if change else "green for a high index value, brown for a low one",
        },
        "provenance": {"before": before, "after": after, "note": NOTE},
    }

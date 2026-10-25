"""Reads the bands one selected scene needs onto a fixed latitude/longitude grid over the AOI, and converts the stored values to reflectance or Kelvin.

Every scene read over the same AOI lands on the same grid, whatever its tile or projection, which lets before and after be subtracted pixel by pixel and the overlay sit on the AOI's own bounds.
"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Long edge of the grid; a wider view is averaged down to it rather than read at 10 m
MAX_EDGE_PIXELS = 512
NATIVE_PIXEL_M = 10.0
NODATA_WARN_FRACTION = 0.05
WARN_PARTIAL_COVERAGE = "partial_scene_coverage"

FAIL_READER_UNAVAILABLE = "band_reader_unavailable"
FAIL_MISSING_ASSET = "scene_missing_band_asset"
FAIL_ASSET_NOT_ALLOWED = "asset_host_not_allowed"
FAIL_READ_FAILED = "band_read_failed"
FAIL_EMPTY_WINDOW = "aoi_outside_scene"

# Sentinel-2 COGs are public HTTPS; usgs-landsat is requester-pays, read with the runtime role and billed to this account
SENTINEL_PREFIX = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/"
LANDSAT_PREFIX = "s3://usgs-landsat/"
LANDSAT_REGION = "us-west-2"
GDAL_OPTIONS = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "1", "GDAL_HTTP_TIMEOUT": "60"}

Reader = Callable[[Dict[str, Any], List[str], Sequence[float]], Dict[str, Any]]


def _fail(reason: str, detail: str) -> Dict[str, Any]:
    return {"failure": {"reason": reason, "detail": detail}}


def _extent_m(aoi_bbox: Sequence[float]) -> Tuple[float, float]:
    west, south, east, north = (float(v) for v in aoi_bbox)
    height_m = (north - south) * 110_574.0
    width_m = (east - west) * 111_320.0 * math.cos(math.radians((south + north) / 2.0))
    return height_m, width_m


def aoi_grid_shape(aoi_bbox: Sequence[float]) -> Tuple[int, int]:
    """(rows, cols) of the read grid: 10 m pixels, capped at MAX_EDGE_PIXELS on the long edge."""
    height_m, width_m = _extent_m(aoi_bbox)
    rows, cols = max(1.0, height_m / NATIVE_PIXEL_M), max(1.0, width_m / NATIVE_PIXEL_M)
    factor = min(1.0, MAX_EDGE_PIXELS / max(rows, cols))
    return max(1, int(round(rows * factor))), max(1, int(round(cols * factor)))


def pixel_size_m(aoi_bbox: Sequence[float]) -> float:
    """Ground width of one grid pixel in metres."""
    _, width_m = _extent_m(aoi_bbox)
    return round(width_m / aoi_grid_shape(aoi_bbox)[1], 1)


def _gdal_env(href: str):
    import rasterio

    if href.startswith(LANDSAT_PREFIX):
        import boto3
        from rasterio.session import AWSSession

        return rasterio.Env(session=AWSSession(boto3.Session(region_name=LANDSAT_REGION), requester_pays=True), **GDAL_OPTIONS)
    return rasterio.Env(AWS_NO_SIGN_REQUEST="YES", **GDAL_OPTIONS)


def _read_band(scene: Dict[str, Any], band: str, aoi_bbox: Sequence[float]):
    """One band warped onto the AOI grid as a masked array in physical units."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.vrt import WarpedVRT

    href = scene["assets"][band]
    rows, cols = aoi_grid_shape(aoi_bbox)
    transform = from_bounds(*aoi_bbox, cols, rows)
    with _gdal_env(href), rasterio.open(href) as src, WarpedVRT(
        src, crs="EPSG:4326", transform=transform, width=cols, height=rows,
        src_nodata=src.nodata if src.nodata is not None else 0, resampling=Resampling.average,
    ) as vrt:
        values = vrt.read(1, masked=True)
    scaling = (scene.get("asset_scaling") or {}).get(band) or {"scale": 1.0, "offset": 0.0}
    return values.astype("float64") * scaling["scale"] + scaling["offset"]


def _rasterio_reader(scene: Dict[str, Any], bands: List[str], aoi_bbox: Sequence[float]) -> Dict[str, Any]:
    import numpy as np
    import rasterio

    # Each band is a separate COG, read together
    try:
        with ThreadPoolExecutor(len(bands)) as pool:
            grids = dict(zip(bands, pool.map(lambda b: _read_band(scene, b, aoi_bbox), bands)))
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        return _fail(FAIL_READ_FAILED, f"reading scene {scene.get('id')} failed: {exc}")

    nodata_fraction = max(float(np.ma.count_masked(g)) / g.size for g in grids.values())
    if nodata_fraction >= 1.0:
        return _fail(FAIL_EMPTY_WINDOW, f"scene {scene.get('id')} has no pixels over the area")
    return {
        "band_data": {b: g.filled(np.nan) for b, g in grids.items()},
        "nodata_fraction": round(nodata_fraction, 4),
        "warnings": [WARN_PARTIAL_COVERAGE] if nodata_fraction > NODATA_WARN_FRACTION else [],
    }


_reader: Optional[Reader] = None


def set_reader(reader: Optional[Reader]) -> None:
    """Replace the band reader, for tests; None restores rasterio."""
    global _reader
    _reader = reader


def read_bands(scene: Dict[str, Any], bands: List[str], aoi_bbox: Sequence[float]) -> Dict[str, Any]:
    """{"band_data": {band: grid}, "nodata_fraction", "warnings"} or {"failure": {...}}."""
    if _reader is not None:
        return _reader(scene, bands, aoi_bbox)
    assets = scene.get("assets") or {}
    missing = [b for b in bands if b not in assets]
    if missing:
        return _fail(FAIL_MISSING_ASSET, f"scene {scene.get('id')} has no asset for {missing}")
    elsewhere = [b for b in bands if not assets[b].startswith((SENTINEL_PREFIX, LANDSAT_PREFIX))]
    if elsewhere:
        return _fail(FAIL_ASSET_NOT_ALLOWED, f"scene {scene.get('id')} bands {elsewhere} are not on the Sentinel-2 or Landsat bucket")
    try:
        import rasterio  # noqa: F401
    except ImportError as exc:
        logger.warning("rasterio import failed: %s", exc)
        return _fail(FAIL_READER_UNAVAILABLE, f"rasterio could not be imported: {exc}")
    return _rasterio_reader(scene, bands, aoi_bbox)

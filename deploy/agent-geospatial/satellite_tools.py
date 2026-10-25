"""The geospatial agent's two tools over the map view the user asked about: one index near a date, or the change in an index between two dates, each drawn on the map.

The model chooses only the index and the dates. A scene carrying band_data is used as it is, which keeps tests offline; otherwise pixels are read once, for the scene that wins selection.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from geospatial import band_maths, overlay, raster_source, scene_selection, stac

logger = logging.getLogger(__name__)

# England and Wales with a margin for the sea around the coast
UK_BOUNDS = (-6.5, 49.8, 2.2, 55.9)
# About 24 km east to west; a wider view would read a region's worth of pixels
MAX_SPAN_DEGREES = 0.35
SEARCH_WINDOW_DAYS = 90
CLOUD_MAX_PCT = 10
# First Sentinel-2 L2A scenes over England on Earth Search
EARLIEST_DATE = date(2016, 11, 1)
ZOOM_IN_MESSAGE = "Zoom the map in to an area of England or Wales no wider than about 25 km, then ask again."

FAIL_INVALID = "invalid_argument"
FAIL_NOT_KELVIN = "thermal_scaling_not_applied"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SCENE_KEYS = ("satellite", "scene_id", "capture_date", "cloud_cover_pct", "processing_baseline",
               "requested_date", "requested_window_days", "actual_offset_days")


def aoi_from_coordinates(coordinates: Any) -> Optional[List[float]]:
    """[west, south, east, north] for the map view's [[lng, lat], ...] ring, or None when it isn't one, is outside England and Wales, or is too wide."""
    try:
        points = [(float(p[0]), float(p[1])) for p in coordinates]
    except (TypeError, ValueError, IndexError):
        return None
    if not points:
        return None
    lngs, lats = [p[0] for p in points], [p[1] for p in points]
    west, east, south, north = min(lngs), max(lngs), min(lats), max(lats)
    w_min, s_min, e_max, n_max = UK_BOUNDS
    if not (w_min <= west < east <= e_max and s_min <= south < north <= n_max):
        return None
    if east - west > MAX_SPAN_DEGREES or north - south > MAX_SPAN_DEGREES:
        return None
    return [round(west, 5), round(south, 5), round(east, 5), round(north, 5)]


def describe_area(bbox: Sequence[float]) -> str:
    west, south, east, north = bbox
    return f"{south:.4f}N {west:.4f}E to {north:.4f}N {east:.4f}E, {band_maths.aoi_area_ha(bbox):,.0f} ha (west, south, east, north = {list(bbox)})"


def _fail(reason: str, detail: str, **extra: Any) -> Dict[str, Any]:
    return {"failure": {"reason": reason, "detail": detail}, **extra}


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        return EARLIEST_DATE <= date.fromisoformat(value) <= date.today()
    except ValueError:
        return False


def _scene(provenance_inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: provenance_inputs.get(k) for k in _SCENE_KEYS}


def _bands(scene: Dict[str, Any], index: str, bbox: Sequence[float]) -> Dict[str, Any]:
    """{"band_data", "warnings"} for the selected scene, or a failure."""
    needed = band_maths.required_bands(index)
    injected = scene.get("band_data") or {}
    if all(b in injected for b in needed):
        return {"band_data": {b: injected[b] for b in needed}, "warnings": []}
    read = raster_source.read_bands(scene, needed, bbox)
    if "failure" in read:
        return read
    scaling = scene.get("asset_scaling") or {}
    logger.info("Read %s %s scaling=%s nodata=%s", scene["id"], needed, {b: scaling.get(b) for b in needed}, read["nodata_fraction"])
    return {"band_data": read["band_data"], "warnings": read["warnings"]}


class SatelliteTools:
    """The tools for one request: the AOI comes from the map, never from the model, and overlays go to emit_overlay."""

    def __init__(self, bbox: List[float], emit_overlay: Callable[[Dict[str, Any]], None]) -> None:
        self.bbox = bbox
        self.emit_overlay = emit_overlay

    def _search(self, provider: str, target: str) -> Dict[str, Any]:
        return stac.search_scenes(self.bbox, provider, target, window_days=SEARCH_WINDOW_DAYS)

    def _draw(self, index: str, grid: np.ndarray, after: Dict[str, Any], before: Optional[Dict[str, Any]] = None) -> str:
        """Send the overlay to the page and say what it shows."""
        event = overlay.overlay_event(self.bbox, index, grid, after, before)
        if not event:
            return "not drawn"
        self.emit_overlay(event)
        return "drawn: " + event["legend"]["meaning"]

    def _result(self, index: str, stats: Dict[str, Any], warnings: List[str], drawn: str, **scenes: Any) -> Dict[str, Any]:
        return {
            "index": index,
            **scenes,
            "area_ha": round(band_maths.aoi_area_ha(self.bbox), 1),
            "pixel_size_m": raster_source.pixel_size_m(self.bbox),
            "statistics": stats,
            "warnings": warnings,
            "interpretation_limit": band_maths.INTERPRETATION_LIMIT,
            "map": drawn,
        }

    def analyse_area(self, index: str, target_date: str) -> Dict[str, Any]:
        if index not in band_maths.SINGLE_INDICES:
            return _fail(FAIL_INVALID, f"index must be one of {list(band_maths.SINGLE_INDICES)}")
        if not _valid_date(target_date):
            return _fail(FAIL_INVALID, f"date must be YYYY-MM-DD between {EARLIEST_DATE.isoformat()} and today")
        found = self._search("landsat" if index == "thermal" else "sentinel-2", target_date)
        if "failure" in found:
            return found
        selection = scene_selection.select_scene(found["scenes"], self.bbox, index, target_date, CLOUD_MAX_PCT)
        if "failure" in selection:
            return selection
        loaded = _bands(selection["selected"], index, self.bbox)
        if "failure" in loaded:
            return loaded
        warnings = list(dict.fromkeys(selection["warnings"] + loaded["warnings"]))
        scene = _scene(selection["provenance_inputs"])
        area_ha = band_maths.aoi_area_ha(self.bbox)

        if index == "thermal":
            kelvin = np.asarray(loaded["band_data"]["lwir11"], dtype="float64")
            median = float(np.nanmedian(kelvin)) if np.isfinite(kelvin).any() else float("nan")
            if not 200 < median < 350:
                return _fail(FAIL_NOT_KELVIN, f"lwir11 median is {median:.0f}, not a surface temperature in Kelvin")
            return self._result(index, band_maths.statistics(kelvin - 273.15, area_ha=area_ha), warnings, "not drawn", scene=scene)

        grid = band_maths.compute_index(index, loaded["band_data"])
        return self._result(index, band_maths.statistics(grid, index, area_ha), warnings, self._draw(index, grid, scene), scene=scene)

    def compare_change(self, index: str, before_date: str, after_date: str) -> Dict[str, Any]:
        if index not in band_maths.CHANGE_INDICES:
            return _fail(FAIL_INVALID, f"index must be one of {list(band_maths.CHANGE_INDICES)}")
        if not (_valid_date(before_date) and _valid_date(after_date)):
            return _fail(FAIL_INVALID, f"dates must be YYYY-MM-DD between {EARLIEST_DATE.isoformat()} and today")
        if before_date >= after_date:
            return _fail(FAIL_INVALID, "before_date must be earlier than after_date")

        # The two searches, then the two scenes' reads, are independent; each pair takes the time of its slower half
        with ThreadPoolExecutor(2) as pool:
            found = list(pool.map(lambda d: self._search("sentinel-2", d), (before_date, after_date)))
        for stage, f in zip(("before", "after"), found):
            if "failure" in f:
                return {**f, "stage": stage}
        pair = scene_selection.select_change_pair(found[0]["scenes"], found[1]["scenes"], self.bbox, index, before_date, after_date, CLOUD_MAX_PCT)
        if "failure" in pair:
            return pair
        with ThreadPoolExecutor(2) as pool:
            loaded = list(pool.map(lambda side: _bands(pair[side]["selected"], index, self.bbox), ("before", "after")))
        for stage, bands in zip(("before", "after"), loaded):
            if "failure" in bands:
                return {**bands, "stage": stage}

        warnings = list(dict.fromkeys(pair["warnings"] + loaded[0]["warnings"] + loaded[1]["warnings"]))
        before_grid, after_grid = (band_maths.compute_index(index, bands["band_data"]) for bands in loaded)
        change = after_grid - before_grid
        before, after = (_scene(pair[side]["provenance_inputs"]) for side in ("before", "after"))
        return self._result(
            index, band_maths.statistics(change, "change", band_maths.aoi_area_ha(self.bbox)), warnings, self._draw(index, change, after, before),
            before_scene=before, after_scene=after,
            mean_before=band_maths.statistics(before_grid)["mean"], mean_after=band_maths.statistics(after_grid)["mean"],
            seasonal_mismatch=pair["seasonal_mismatch"],
        )

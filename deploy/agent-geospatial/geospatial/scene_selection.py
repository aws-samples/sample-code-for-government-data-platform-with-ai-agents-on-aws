"""Picks one scene, or a before and after pair, from candidate scene dicts: required bands, a widening date window, a cloud ceiling, then AOI overlap, cloud cover, date and id.

Overlap uses the item's data footprint, not its tile box: a Sentinel-2 tile at a swath edge or a UTM zone boundary has a full box but pixels over only part of it.
"""
from datetime import date
from typing import Any, Dict, List, Sequence, Tuple

from .band_maths import required_bands

# Days either side of the requested date, tried in order
DATE_WINDOW_SEQUENCE = (30, 60, 90)
DEFAULT_CLOUD_MAX = 10
# Two captures within this many days of each other in the calendar year are the same season
SEASON_BAND_DAYS = 45

FAIL_NO_BANDS = "no_scene_with_required_bands"
FAIL_NO_WINDOW = "no_scene_in_window"
WARN_CLOUD = "cloud_quality_uncertain"
WARN_SEASON = "seasonal_mismatch"


def _offset_days(scene_date: str, requested: str) -> int:
    return (date.fromisoformat(scene_date) - date.fromisoformat(requested)).days


def _clip_ring(ring: Sequence[Sequence[float]], aoi_bbox: Sequence[float]) -> List[Tuple[float, float]]:
    """Sutherland-Hodgman clip of a [lon, lat] ring to the AOI box."""
    west, south, east, north = aoi_bbox
    edges = [
        (lambda p: p[0] >= west, lambda a, b: (west, a[1] + (b[1] - a[1]) * (west - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= east, lambda a, b: (east, a[1] + (b[1] - a[1]) * (east - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= south, lambda a, b: (a[0] + (b[0] - a[0]) * (south - a[1]) / (b[1] - a[1]), south)),
        (lambda p: p[1] <= north, lambda a, b: (a[0] + (b[0] - a[0]) * (north - a[1]) / (b[1] - a[1]), north)),
    ]
    points = [(float(p[0]), float(p[1])) for p in ring]
    for inside, cross in edges:
        if not points:
            break
        clipped = []
        for i, current in enumerate(points):
            previous = points[i - 1]
            if inside(current):
                if not inside(previous):
                    clipped.append(cross(previous, current))
                clipped.append(current)
            elif inside(previous):
                clipped.append(cross(previous, current))
        points = clipped
    return points


def _ring_area(points: Sequence[Tuple[float, float]]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, list(points[1:]) + list(points[:1])))) / 2.0


def overlap_fraction(scene: Dict[str, Any], aoi_bbox: Sequence[float]) -> float:
    """Share of the AOI the scene's data footprint covers, in planar degrees; its bbox stands in when the item has no footprint."""
    west, south, east, north = aoi_bbox
    aoi_area = (east - west) * (north - south)
    if aoi_area <= 0:
        return 0.0
    sw, ss, se, sn = scene["bbox"]
    rings = scene.get("footprint") or [[(sw, ss), (se, ss), (se, sn), (sw, sn)]]
    return min(1.0, sum(_ring_area(_clip_ring(ring, aoi_bbox)) for ring in rings) / aoi_area)


def _rank_key(scene: Dict[str, Any], aoi_bbox: Sequence[float], requested: str):
    """Smaller is better: more overlap, then less cloud, then closer date, then scene id."""
    return (
        -round(overlap_fraction(scene, aoi_bbox), 3),
        float(scene.get("cloud_cover_pct", 0.0)),
        abs(_offset_days(scene["datetime"], requested)),
        str(scene["id"]),
    )


def _provenance_inputs(scene: Dict[str, Any], requested: str, window_days: int) -> Dict[str, Any]:
    return {
        "satellite": scene.get("provider"),
        "collection": scene.get("collection"),
        "scene_id": scene.get("id"),
        "capture_date": scene.get("datetime"),
        "cloud_cover_pct": scene.get("cloud_cover_pct"),
        "processing_baseline": scene.get("processing_baseline"),
        "grid_cell": scene.get("grid_cell"),
        "requested_date": requested,
        "requested_window_days": window_days,
        "actual_offset_days": _offset_days(scene["datetime"], requested),
    }


def select_scene(
    scenes: List[Dict[str, Any]],
    aoi_bbox: Sequence[float],
    index: str,
    target_date: str,
    cloud_cover_max_pct: float = DEFAULT_CLOUD_MAX,
) -> Dict[str, Any]:
    """{"selected", "provenance_inputs", "warnings", "window_days", "overlap_fraction"} or {"failure": {"reason", "detail"}}.

    When every scene in the window is over the cloud ceiling, the clearest is used with a cloud_quality_uncertain warning.
    """
    needed = set(required_bands(index))
    with_bands = [s for s in scenes if needed.issubset(set(s.get("bands", ())))]
    if not with_bands:
        return {"failure": {"reason": FAIL_NO_BANDS, "detail": f"no scene has bands {sorted(needed)}"}}

    windowed, used_window = [], DATE_WINDOW_SEQUENCE[-1]
    for days in DATE_WINDOW_SEQUENCE:
        windowed = [s for s in with_bands if abs(_offset_days(s["datetime"], target_date)) <= days]
        if windowed:
            used_window = days
            break
    if not windowed:
        return {"failure": {"reason": FAIL_NO_WINDOW, "detail": f"no scene within {DATE_WINDOW_SEQUENCE[-1]} days of {target_date}"}}

    warnings: List[str] = []
    candidates = [s for s in windowed if float(s.get("cloud_cover_pct", 0.0)) <= cloud_cover_max_pct]
    if not candidates:
        warnings.append(WARN_CLOUD)
        candidates = windowed

    best = min(candidates, key=lambda s: _rank_key(s, aoi_bbox, target_date))
    return {
        "selected": best,
        "provenance_inputs": _provenance_inputs(best, target_date, used_window),
        "warnings": warnings,
        "window_days": used_window,
        "overlap_fraction": overlap_fraction(best, aoi_bbox),
    }


def _same_season(a: str, b: str) -> bool:
    """Day-of-year distance, wrapping at the year end, within SEASON_BAND_DAYS."""
    da, db = date.fromisoformat(a).timetuple().tm_yday, date.fromisoformat(b).timetuple().tm_yday
    return min(abs(da - db), 366 - abs(da - db)) <= SEASON_BAND_DAYS


def select_change_pair(
    before_scenes: List[Dict[str, Any]],
    after_scenes: List[Dict[str, Any]],
    aoi_bbox: Sequence[float],
    index: str,
    before_date: str,
    after_date: str,
    cloud_cover_max_pct: float = DEFAULT_CLOUD_MAX,
) -> Dict[str, Any]:
    """{"before", "after", "seasonal_mismatch", "warnings"} or {"failure", "stage"}. A season mismatch is a warning, not a failure."""
    before = select_scene(before_scenes, aoi_bbox, index, before_date, cloud_cover_max_pct)
    if "failure" in before:
        return {"failure": before["failure"], "stage": "before"}
    after = select_scene(after_scenes, aoi_bbox, index, after_date, cloud_cover_max_pct)
    if "failure" in after:
        return {"failure": after["failure"], "stage": "after"}

    warnings = list(dict.fromkeys(before["warnings"] + after["warnings"]))
    mismatch = not _same_season(before["selected"]["datetime"], after["selected"]["datetime"])
    if mismatch:
        warnings.append(WARN_SEASON)
    return {"before": before, "after": after, "seasonal_mismatch": mismatch, "warnings": warnings}

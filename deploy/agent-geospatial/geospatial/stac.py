"""Searches the public Earth Search STAC API for Sentinel-2 and Landsat scenes over an area and maps each item to a scene dict the selector ranks."""
import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence

STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
SEARCH_URL = f"{STAC_ENDPOINT}/search"

PROVIDER_COLLECTIONS: Dict[str, str] = {
    "sentinel-2": "sentinel-2-l2a",
    "landsat": "landsat-c2-l2",
}

# Band name the index maths asks for, to the asset key each collection publishes it under
COLLECTION_BAND_ASSETS: Dict[str, Dict[str, str]] = {
    "sentinel-2-l2a": {"red": "red", "green": "green", "blue": "blue", "nir": "nir", "swir16": "swir16", "swir22": "swir22"},
    "landsat-c2-l2": {"red": "red", "green": "green", "blue": "blue", "nir": "nir08", "swir16": "swir16", "swir22": "swir22", "lwir11": "lwir11"},
}

MAX_LIMIT = 50
# Results come newest first; reading every page keeps the early dates of a wide window
MAX_PAGES = 8
HTTP_TIMEOUT_SECONDS = 20

FAIL_UNKNOWN_PROVIDER = "unknown_provider"
FAIL_STAC_UNAVAILABLE = "stac_unavailable"
FAIL_STAC_RESPONSE = "stac_response_invalid"


class StacError(RuntimeError):
    pass


Transport = Callable[[str, bytes], Dict[str, Any]]


def _default_transport(url: str, body: bytes) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/geo+json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # nosec B310 - url is always SEARCH_URL, an https constant
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StacError(f"STAC request failed: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StacError(f"STAC response was not JSON: {exc}") from exc


_transport: Optional[Transport] = None


def set_transport(transport: Optional[Transport]) -> None:
    """Replace the HTTP transport, for tests; None restores the live one."""
    global _transport
    _transport = transport


def _fail(reason: str, detail: str) -> Dict[str, Any]:
    return {"failure": {"reason": reason, "detail": detail}}


def _date_range(target_date: str, window_days: int) -> str:
    centre = date.fromisoformat(target_date)
    start, end = centre - timedelta(days=window_days), centre + timedelta(days=window_days)
    return f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"


def _grid_cell(properties: Dict[str, Any]) -> Optional[str]:
    code = properties.get("grid:code")
    if isinstance(code, str) and code:
        return code
    zone, band, square = (properties.get(k) for k in ("mgrs:utm_zone", "mgrs:latitude_band", "mgrs:grid_square"))
    if zone and band and square:
        return f"{zone}{band}{square}"
    path, row = properties.get("landsat:wrs_path"), properties.get("landsat:wrs_row")
    return f"{path}/{row}" if path and row else None


def _asset_scaling(asset: Dict[str, Any], offset_in_pixels: bool) -> Dict[str, float]:
    """Scale and offset turning the asset's stored values into reflectance or Kelvin.

    Earth Search writes the Sentinel-2 baseline 04.00 offset into the pixels and still declares it, flagged by earthsearch:boa_offset_applied.
    """
    raster_band = (asset.get("raster:bands") or [{}])[0]
    scale = raster_band.get("scale")
    offset = 0 if offset_in_pixels else raster_band.get("offset")
    return {"scale": float(scale) if scale is not None else 1.0, "offset": float(offset) if offset is not None else 0.0}


def _footprint(geometry: Any) -> Optional[List[List[List[float]]]]:
    """Outer rings of a Polygon or MultiPolygon item geometry, or None."""
    if not isinstance(geometry, dict):
        return None
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        rings = coords[:1]
    elif geometry.get("type") == "MultiPolygon":
        rings = [polygon[0] for polygon in coords if polygon]
    else:
        return None
    try:
        return [[[float(p[0]), float(p[1])] for p in ring] for ring in rings] or None
    except (TypeError, ValueError, IndexError):
        return None


def item_to_scene(item: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    """The scene dict for one STAC item, or None when it has no id, bbox or capture date."""
    scene_id, bbox = item.get("id"), item.get("bbox")
    properties = item.get("properties") or {}
    captured = properties.get("datetime") or properties.get("start_datetime")
    if not scene_id or not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not captured:
        return None

    collection = item.get("collection") or PROVIDER_COLLECTIONS.get(provider, "")
    item_assets = item.get("assets") or {}
    offset_in_pixels = bool(properties.get("earthsearch:boa_offset_applied"))
    assets: Dict[str, str] = {}
    scaling: Dict[str, Dict[str, float]] = {}
    for band, key in COLLECTION_BAND_ASSETS.get(collection, {}).items():
        asset = item_assets.get(key)
        if isinstance(asset, dict) and asset.get("href"):
            assets[band] = asset["href"]
            scaling[band] = _asset_scaling(asset, offset_in_pixels)

    cloud_cover = properties.get("eo:cloud_cover")
    return {
        "id": str(scene_id),
        "provider": provider,
        "collection": collection,
        "datetime": str(captured)[:10],
        "cloud_cover_pct": round(float(cloud_cover), 2) if cloud_cover is not None else 0.0,
        "bbox": [float(v) for v in bbox],
        "footprint": _footprint(item.get("geometry")),
        "grid_cell": _grid_cell(properties),
        "processing_baseline": properties.get("s2:processing_baseline"),
        "bands": set(assets),
        "assets": assets,
        "asset_scaling": scaling,
    }


def _next_page_body(payload: Dict[str, Any], first_body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The body for the next page from a POST 'next' link back to the same endpoint, or None."""
    for link in payload.get("links") or []:
        if not isinstance(link, dict) or link.get("rel") != "next":
            continue
        if link.get("method", "GET").upper() != "POST" or link.get("href") != SEARCH_URL:
            return None
        body = link.get("body")
        if not isinstance(body, dict) or "next" not in body:
            return None
        merged = dict(first_body) if link.get("merge") else {}
        merged.update(body)
        return merged
    return None


def search_scenes(aoi_bbox: Sequence[float], provider: str, target_date: str, window_days: int = 90) -> Dict[str, Any]:
    """{"scenes": [...], "window_days"} for every scene within window_days of target_date, unranked, or {"failure": {...}}."""
    collection = PROVIDER_COLLECTIONS.get(provider)
    if collection is None:
        return _fail(FAIL_UNKNOWN_PROVIDER, f"provider must be one of {sorted(PROVIDER_COLLECTIONS)}, got {provider!r}")

    body: Dict[str, Any] = {
        "collections": [collection],
        "bbox": [float(v) for v in aoi_bbox],
        "datetime": _date_range(target_date, window_days),
        "limit": MAX_LIMIT,
    }
    transport = _transport or _default_transport
    features: List[Dict[str, Any]] = []
    request_body: Optional[Dict[str, Any]] = body
    for _ in range(MAX_PAGES):
        try:
            payload = transport(SEARCH_URL, json.dumps(request_body).encode("utf-8"))
        except StacError as exc:
            return _fail(FAIL_STAC_UNAVAILABLE, str(exc))
        page = payload.get("features")
        if not isinstance(page, list):
            return _fail(FAIL_STAC_RESPONSE, "response had no 'features' list")
        features.extend(page)
        request_body = _next_page_body(payload, body)
        if request_body is None:
            break

    scenes = [s for s in (item_to_scene(item, provider) for item in features) if s]
    return {"scenes": scenes, "window_days": window_days}

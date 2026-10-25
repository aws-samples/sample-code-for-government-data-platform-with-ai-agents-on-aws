"""Spectral index maths over reflectance grids: normalised-difference indices, change between two dates, surface temperature and banded areas."""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Each index is (a - b) / (a + b) over the band pair given
INDEX_BANDS: Dict[str, Tuple[str, str]] = {
    "NDVI": ("nir", "red"),
    "NDWI": ("green", "nir"),
    "NDBI": ("swir16", "nir"),
    "NBR": ("nir", "swir22"),
}
SINGLE_INDICES = ("NDVI", "NDWI", "NDBI", "NBR", "thermal")
CHANGE_INDICES = ("NDVI", "NDBI", "NBR")

# Bands are (label, low, high), low inclusive. Labels describe the index magnitude, not land cover.
INDEX_CLASSES: Dict[str, List[Tuple[str, float, float]]] = {
    "NDVI": [
        ("water_or_bare", -1.00, 0.00),
        ("bare_or_sparse", 0.00, 0.15),
        ("low_vegetation_index", 0.15, 0.33),
        ("moderate_vegetation_index", 0.33, 0.50),
        ("high_vegetation_index", 0.50, 1.00),
    ],
    "NDWI": [
        ("dry_index", -1.00, -0.30),
        ("low_moisture_index", -0.30, 0.00),
        ("moderate_moisture_index", 0.00, 0.20),
        ("high_moisture_index", 0.20, 1.00),
    ],
    "NDBI": [
        ("low_builtup_index", -1.00, 0.00),
        ("moderate_builtup_index", 0.00, 0.15),
        ("high_builtup_index", 0.15, 1.00),
    ],
    "NBR": [
        ("low_index", -1.00, 0.00),
        ("moderate_index", 0.00, 0.27),
        ("high_index", 0.27, 1.00),
    ],
    # After minus before: a burn or vegetation loss is a fall
    "change": [
        ("index_fell", -2.00, -0.10),
        ("little_change", -0.10, 0.10),
        ("index_rose", 0.10, 2.00),
    ],
}

INTERPRETATION_LIMIT = (
    "Index values and banded areas only. Bands describe the index magnitude, "
    "not a verified land-cover, building, or population claim."
)


def required_bands(index: str) -> List[str]:
    """Bands an index needs, e.g. NDVI needs nir and red, thermal needs lwir11."""
    if index == "thermal":
        return ["lwir11"]
    return list(INDEX_BANDS[index])


def compute_index(index: str, bands: Dict[str, Any]) -> np.ndarray:
    """The index grid from reflectance bands; nodata and zero-sum pixels are NaN."""
    hi, lo = INDEX_BANDS[index]
    missing = [b for b in (hi, lo) if b not in bands]
    if missing:
        raise ValueError(f"missing bands for {index}: {missing}")
    a = np.asarray(bands[hi], dtype="float64")
    b = np.asarray(bands[lo], dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (a - b) / (a + b)
    ratio[~np.isfinite(ratio)] = np.nan
    return np.clip(ratio, -1.0, 1.0)


def statistics(values: Any, classes: Optional[str] = None, area_ha: Optional[float] = None) -> Dict[str, Any]:
    """Min, max, mean and valid-pixel share of a grid, plus each band's share and area when classes names a set in INDEX_CLASSES.

    Shares are of every pixel in the area, with a no_data share for pixels the scene didn't cover, which keeps the areas summing to the AOI.
    """
    grid = np.asarray(values, dtype="float64")
    total = int(grid.size)
    finite = grid[np.isfinite(grid)]
    result: Dict[str, Any] = {
        "valid_fraction": round(finite.size / total, 4) if total else 0.0,
        "pixel_count": total,
    }
    if not finite.size:
        return {**result, "min": None, "max": None, "mean": None}
    result.update({
        "min": round(float(finite.min()), 4),
        "max": round(float(finite.max()), 4),
        "mean": round(float(finite.mean()), 4),
    })
    if classes:
        bands = INDEX_CLASSES[classes]
        fractions = {}
        for i, (label, low, high) in enumerate(bands):
            upper = finite <= high if i == len(bands) - 1 else finite < high
            fractions[label] = float(np.count_nonzero((finite >= low) & upper)) / total
        fractions["no_data"] = (total - finite.size) / total
        result["fraction_by_class"] = {k: round(v, 4) for k, v in fractions.items()}
        if area_ha is not None:
            result["area_ha_by_class"] = {k: round(v * area_ha, 1) for k, v in fractions.items()}
    return result


def aoi_area_ha(bbox: Sequence[float]) -> float:
    """Area of a [west, south, east, north] box in hectares, with longitude scaled by the cosine of the mean latitude."""
    west, south, east, north = bbox
    metres_per_degree = 111_320.0
    height_m = abs(north - south) * metres_per_degree
    width_m = abs(east - west) * metres_per_degree * math.cos(math.radians((south + north) / 2.0))
    return width_m * height_m / 10_000.0

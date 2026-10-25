"""Unit tests for the geospatial agent's bounded satellite tools. No network: STAC and band reads are stubbed.

    python -m pytest tests/test_geospatial.py
"""
import base64
import json
import os
import struct
import sys
import zlib
from datetime import date, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy", "agent-geospatial"))

import satellite_tools  # noqa: E402
from geospatial import band_maths, overlay, raster_source, scene_selection, stac  # noqa: E402

AOI = [-1.90, 52.40, -1.80, 52.50]
FULL = [-1.95, 52.35, -1.75, 52.55]
HALF = [-1.90, 52.45, -1.80, 52.55]
VIEW = [[-1.50, 52.29], [-1.48, 52.29], [-1.48, 52.30], [-1.50, 52.30], [-1.50, 52.29]]


@pytest.fixture(autouse=True)
def _reset_seams():
    yield
    raster_source.set_reader(None)
    stac.set_transport(None)


def _scene(sid, dt, cloud=5, bbox=FULL, bands=("nir", "red"), band_data=None, provider="sentinel-2", scaling=None):
    scene = {"id": sid, "provider": provider, "collection": "sentinel-2-l2a", "datetime": dt, "cloud_cover_pct": cloud,
             "bbox": bbox, "grid_cell": "A", "bands": set(bands), "assets": {b: f"https://sentinel-cogs.s3.us-west-2.amazonaws.com/{sid}/{b}.tif" for b in bands}}
    if band_data is not None:
        scene["band_data"] = band_data
    if scaling is not None:
        scene["asset_scaling"] = scaling
    return scene


def _tools(overlays=None, scenes=None):
    """SatelliteTools over the test view, with the STAC search replaced by a fixed scene list per date."""
    tools = satellite_tools.SatelliteTools([-1.5, 52.29, -1.48, 52.3], (overlays if overlays is not None else []).append)
    if scenes is not None:
        tools._search = lambda provider, target: {"scenes": scenes(provider, target)}
    return tools


def _decode_png(b64):
    data = base64.b64decode(b64)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + width * 4
    return width, height, [[tuple(raw[y * stride + 1 + x * 4:y * stride + 5 + x * 4]) for x in range(width)] for y in range(height)]


class _Reader:
    """Stands in for rasterio: fixed grids per band, with the scene's scaling applied and the read scenes recorded."""

    def __init__(self, grids, nodata_fraction=0.0, failure=None):
        self.grids, self.nodata_fraction, self.failure, self.calls = grids, nodata_fraction, failure, []

    def __call__(self, scene, bands, aoi_bbox):
        self.calls.append(scene["id"])
        if self.failure:
            return {"failure": self.failure}
        scaling = scene.get("asset_scaling") or {}
        data = {b: np.asarray(self.grids[b], dtype="float64") * scaling.get(b, {}).get("scale", 1.0) + scaling.get(b, {}).get("offset", 0.0) for b in bands}
        warnings = [raster_source.WARN_PARTIAL_COVERAGE] if self.nodata_fraction > raster_source.NODATA_WARN_FRACTION else []
        return {"band_data": data, "nodata_fraction": self.nodata_fraction, "warnings": warnings}


# Band maths

@pytest.mark.parametrize("index,bands,expected", [
    ("NDVI", {"nir": [[0.8]], "red": [[0.2]]}, 0.6),
    ("NDWI", {"green": [[0.5]], "nir": [[0.1]]}, 0.4 / 0.6),
    ("NDBI", {"swir16": [[0.4]], "nir": [[0.2]]}, 0.2 / 0.6),
    ("NBR", {"nir": [[0.6]], "swir22": [[0.2]]}, 0.5),
])
def test_index_known_values(index, bands, expected):
    assert band_maths.compute_index(index, bands)[0, 0] == pytest.approx(expected)


def test_nodata_and_zero_sum_pixels_are_nan_and_left_out_of_the_mean():
    grid = band_maths.compute_index("NDVI", {"nir": [[0.8, np.nan, 0.0]], "red": [[0.2, 0.1, 0.0]]})
    assert grid[0, 0] == pytest.approx(0.6)
    assert np.isnan(grid[0, 1]) and np.isnan(grid[0, 2])
    stats = band_maths.statistics(grid, "NDVI", area_ha=30.0)
    assert stats["mean"] == pytest.approx(0.6)
    assert stats["valid_fraction"] == pytest.approx(1 / 3, abs=1e-4)


def test_class_areas_sum_to_the_aoi_including_no_data():
    grid = band_maths.compute_index("NDVI", {"nir": [[0.8, 0.2, np.nan, 0.5]], "red": [[0.2, 0.2, 0.1, 0.1]]})
    stats = band_maths.statistics(grid, "NDVI", area_ha=100.0)
    assert sum(stats["area_ha_by_class"].values()) == pytest.approx(100.0, abs=0.2)
    assert stats["area_ha_by_class"]["no_data"] == pytest.approx(25.0)


def test_change_classes_follow_the_sign():
    stats = band_maths.statistics(np.array([[0.2, 0.55, 0.8]]) - np.array([[0.5, 0.5, 0.5]]), "change")
    assert [stats["fraction_by_class"][k] for k in ("index_fell", "little_change", "index_rose")] == pytest.approx([1 / 3] * 3, abs=1e-4)


def test_missing_band_raises():
    with pytest.raises(ValueError):
        band_maths.compute_index("NDVI", {"nir": [[0.5]]})


def test_aoi_area_is_about_right_for_a_small_box():
    # 0.1 degree of latitude is about 11.1 km, 0.1 degree of longitude at 52.45N about 6.8 km
    assert band_maths.aoi_area_ha(AOI) == pytest.approx(7_570, rel=0.02)


# Scene selection

def test_selection_needs_the_index_bands():
    out = scene_selection.select_scene([_scene("s1", "2024-06-15", bands=("red", "green"))], AOI, "NDVI", "2024-06-15")
    assert out["failure"]["reason"] == scene_selection.FAIL_NO_BANDS


def test_selection_widens_the_window():
    out = scene_selection.select_scene([_scene("s1", "2024-08-09")], AOI, "NDVI", "2024-06-15")
    assert out["window_days"] == 60
    assert out["provenance_inputs"]["actual_offset_days"] == 55


def test_selection_fails_outside_the_widest_window():
    out = scene_selection.select_scene([_scene("s1", "2025-01-01")], AOI, "NDVI", "2024-06-15")
    assert out["failure"]["reason"] == scene_selection.FAIL_NO_WINDOW


def test_overlap_wins_over_cloud_then_cloud_over_date():
    full, half = _scene("full", "2024-06-15", cloud=8), _scene("half", "2024-06-15", cloud=2, bbox=HALF)
    assert scene_selection.select_scene([half, full], AOI, "NDVI", "2024-06-15")["selected"]["id"] == "full"
    near, clear = _scene("near", "2024-06-15", cloud=9), _scene("clear", "2024-06-20", cloud=3)
    assert scene_selection.select_scene([near, clear], AOI, "NDVI", "2024-06-15")["selected"]["id"] == "clear"


def test_a_tile_whose_pixels_stop_short_loses_to_one_that_covers_the_area():
    # Both tile boxes cover the AOI, but the edge tile's data footprint covers only its west half
    edge = _scene("edge", "2024-06-15", cloud=0)
    edge["footprint"] = [[[-1.95, 52.35], [-1.85, 52.35], [-1.85, 52.55], [-1.95, 52.55], [-1.95, 52.35]]]
    whole = _scene("whole", "2024-06-15", cloud=6)
    assert scene_selection.select_scene([edge, whole], AOI, "NDVI", "2024-06-15")["selected"]["id"] == "whole"
    assert scene_selection.overlap_fraction(edge, AOI) == pytest.approx(0.5)
    assert scene_selection.overlap_fraction(whole, AOI) == pytest.approx(1.0)


def test_cloud_ceiling_relaxes_with_a_warning():
    out = scene_selection.select_scene([_scene("a", "2024-06-15", cloud=40), _scene("b", "2024-06-15", cloud=25)], AOI, "NDVI", "2024-06-15")
    assert out["selected"]["id"] == "b"
    assert scene_selection.WARN_CLOUD in out["warnings"]


def test_tie_break_is_deterministic():
    a, b = _scene("zzz", "2024-06-15"), _scene("aaa", "2024-06-15")
    assert scene_selection.select_scene([a, b], AOI, "NDVI", "2024-06-15")["selected"]["id"] == "aaa"
    assert scene_selection.select_scene([b, a], AOI, "NDVI", "2024-06-15")["selected"]["id"] == "aaa"


def test_season_match_and_mismatch():
    matched = scene_selection.select_change_pair([_scene("b", "2023-06-10")], [_scene("a", "2024-06-20")], AOI, "NDVI", "2023-06-10", "2024-06-20")
    assert matched["seasonal_mismatch"] is False
    mismatched = scene_selection.select_change_pair([_scene("b", "2023-06-10")], [_scene("a", "2024-01-15")], AOI, "NDVI", "2023-06-10", "2024-01-15")
    assert mismatched["seasonal_mismatch"] is True
    assert scene_selection.WARN_SEASON in mismatched["warnings"]


# STAC

def _item(item_id="S2B_30UYC_20240729_0_L2A", collection="sentinel-2-l2a", captured="2024-07-29T11:06:00Z", cloud=4.2,
          offset_applied=True, offset=-0.1, scale=0.0001, keys=("red", "green", "blue", "nir", "swir16", "swir22")):
    props = {"datetime": captured, "eo:cloud_cover": cloud, "grid:code": "MGRS-30UYC", "s2:processing_baseline": "05.11"}
    if offset_applied is not None:
        props["earthsearch:boa_offset_applied"] = offset_applied
    host = "https://sentinel-cogs.s3.us-west-2.amazonaws.com" if collection == "sentinel-2-l2a" else "s3://usgs-landsat"
    return {"id": item_id, "collection": collection, "bbox": FULL, "properties": props,
            "assets": {k: {"href": f"{host}/{item_id}/{k}.tif", "raster:bands": [{"scale": scale, "offset": offset, "nodata": 0}]} for k in keys}}


class _Transport:
    def __init__(self, pages, href=None):
        self.pages, self.href, self.bodies = pages, href or stac.SEARCH_URL, []

    def __call__(self, url, body):
        self.bodies.append(json.loads(body))
        i = len(self.bodies) - 1
        payload = {"features": self.pages[i], "links": []}
        if i + 1 < len(self.pages):
            payload["links"].append({"rel": "next", "method": "POST", "href": self.href, "merge": False, "body": dict(self.bodies[0], next=f"t{i + 1}")})
        return payload


def test_offset_already_in_the_pixels_is_not_applied_again():
    assert stac.item_to_scene(_item(offset_applied=True), "sentinel-2")["asset_scaling"]["nir"] == {"scale": 0.0001, "offset": 0.0}


def test_declared_offset_is_applied_when_the_pixels_do_not_carry_it():
    assert stac.item_to_scene(_item(offset_applied=False), "sentinel-2")["asset_scaling"]["nir"] == {"scale": 0.0001, "offset": -0.1}
    assert stac.item_to_scene(_item(offset_applied=None, offset=0), "sentinel-2")["asset_scaling"]["red"] == {"scale": 0.0001, "offset": 0.0}


def test_landsat_bands_carry_their_scaling_and_nir_maps_from_nir08():
    item = _item("LC08_L2SP_201024_20240731_02_T1", "landsat-c2-l2", offset_applied=None, scale=0.00341802, offset=149, keys=("red", "nir08", "lwir11"))
    scene = stac.item_to_scene(item, "landsat")
    assert {"nir", "lwir11"} <= scene["bands"]
    assert scene["assets"]["nir"].endswith("nir08.tif")
    assert scene["asset_scaling"]["lwir11"] == {"scale": 0.00341802, "offset": 149.0}


def test_footprint_comes_from_the_item_geometry():
    item = _item()
    item["geometry"] = {"type": "MultiPolygon", "coordinates": [[[[-1.9, 52.4], [-1.8, 52.4], [-1.8, 52.5], [-1.9, 52.4]]]]}
    assert stac.item_to_scene(item, "sentinel-2")["footprint"] == [[[-1.9, 52.4], [-1.8, 52.4], [-1.8, 52.5], [-1.9, 52.4]]]
    assert stac.item_to_scene(_item(), "sentinel-2")["footprint"] is None


def test_search_is_bounded_to_the_collection_and_window():
    transport = _Transport([[_item()]])
    stac.set_transport(transport)
    result = stac.search_scenes(AOI, "sentinel-2", "2024-08-15", window_days=30)
    assert len(result["scenes"]) == 1
    assert transport.bodies[0]["collections"] == ["sentinel-2-l2a"]
    assert transport.bodies[0]["datetime"] == "2024-07-16T00:00:00Z/2024-09-14T23:59:59Z"


def test_unknown_provider_never_reaches_the_endpoint():
    transport = _Transport([[_item()]])
    stac.set_transport(transport)
    assert stac.search_scenes(AOI, "modis", "2024-08-15")["failure"]["reason"] == stac.FAIL_UNKNOWN_PROVIDER
    assert transport.bodies == []


def test_every_page_is_read_and_page_count_is_bounded():
    stac.set_transport(_Transport([[_item("new")], [_item("old", captured="2024-05-01T00:00:00Z")]]))
    assert [s["id"] for s in stac.search_scenes(AOI, "sentinel-2", "2024-06-15")["scenes"]] == ["new", "old"]
    many = _Transport([[_item(f"p{i}")] for i in range(stac.MAX_PAGES + 3)])
    stac.set_transport(many)
    stac.search_scenes(AOI, "sentinel-2", "2024-06-15")
    assert len(many.bodies) == stac.MAX_PAGES


def test_next_link_to_another_host_is_not_followed():
    stac.set_transport(_Transport([[_item("a")], [_item("b")]], href="https://elsewhere.invalid/search"))
    assert [s["id"] for s in stac.search_scenes(AOI, "sentinel-2", "2024-06-15")["scenes"]] == ["a"]


def test_transport_failures_are_structured():
    def boom(url, body):
        raise stac.StacError("down")
    stac.set_transport(boom)
    assert stac.search_scenes(AOI, "sentinel-2", "2024-06-15")["failure"]["reason"] == stac.FAIL_STAC_UNAVAILABLE
    stac.set_transport(lambda url, body: {})
    assert stac.search_scenes(AOI, "sentinel-2", "2024-06-15")["failure"]["reason"] == stac.FAIL_STAC_RESPONSE


# Raster reads

def test_grid_is_10m_for_a_small_area_and_capped_for_a_wide_one():
    small = [-1.0, 52.0, -0.99, 52.005]
    rows, cols = raster_source.aoi_grid_shape(small)
    assert raster_source.pixel_size_m(small) == pytest.approx(10.0, abs=0.5)
    assert rows < cols
    assert max(raster_source.aoi_grid_shape([-1.3, 52.0, -1.0, 52.2])) == raster_source.MAX_EDGE_PIXELS


def test_assets_off_the_two_public_buckets_are_refused_before_any_read():
    scene = {"id": "x", "assets": {"nir": "https://evil.invalid/nir.tif", "red": "https://evil.invalid/red.tif"}}
    assert raster_source.read_bands(scene, ["nir", "red"], AOI)["failure"]["reason"] == raster_source.FAIL_ASSET_NOT_ALLOWED
    assert raster_source.read_bands({"id": "y", "assets": {}}, ["nir"], AOI)["failure"]["reason"] == raster_source.FAIL_MISSING_ASSET


# Overlays

def test_colours_follow_the_sign_and_missing_is_transparent():
    width, height, rows = _decode_png(overlay.png_base64([[0.3, 0.0, -0.3, np.nan]], overlay.CHANGE_CLAMP))
    assert (width, height) == (4, 1)
    rise, flat, fall, missing = rows[0]
    assert rise[1] > rise[0] and fall[0] > fall[2]
    assert flat[:3] == (245, 245, 245)
    assert missing[3] == 0


def test_legend_swatches_match_the_pixels():
    for swatch in overlay.legend_swatches(overlay.CHANGE_CLAMP):
        assert swatch["rgba"] == list(overlay.colours([[swatch["value"]]], overlay.CHANGE_CLAMP)[0, 0])


def test_change_overlay_names_both_scenes():
    before, after = {"scene_id": "b1", "capture_date": "2023-08-09"}, {"scene_id": "a1", "capture_date": "2024-08-10"}
    event = overlay.overlay_event(AOI, "NDVI", np.array([[0.2, -0.2]]), after, before)
    assert event["bounds"] == [[52.40, -1.90], [52.50, -1.80]]
    assert event["legend"]["kind"] == "change"
    assert event["provenance"] == {"before": before, "after": after, "note": overlay.NOTE}
    _decode_png(event["image_data"])
    assert overlay.overlay_event(AOI, "NDVI", np.empty((0, 0)), after) is None


# Agent tools

def test_map_view_becomes_a_bbox():
    assert satellite_tools.aoi_from_coordinates(VIEW) == [-1.5, 52.29, -1.48, 52.3]


@pytest.mark.parametrize("bad", [None, [], "x", [["a", "b"]], [[2.35, 48.85], [2.36, 48.86]], [[-3.0, 52.0], [-1.0, 53.0]]])
def test_unusable_views_are_refused(bad):
    assert satellite_tools.aoi_from_coordinates(bad) is None


def test_bad_arguments_are_refused_before_any_search():
    tools = _tools()
    tools._search = lambda *a: pytest.fail("searched with a bad argument")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for call in (
        lambda: tools.analyse_area("EVI", "2023-07-01"),
        lambda: tools.analyse_area("NDVI", tomorrow),
        lambda: tools.analyse_area("NDVI", "July 2023"),
        lambda: tools.compare_change("NDWI", "2019-07-01", "2023-07-01"),
        lambda: tools.compare_change("NDVI", "2023-07-01", "2019-07-01"),
        lambda: tools.compare_change("NDVI", "2015-07-01", "2019-07-01"),
    ):
        assert call()["failure"]["reason"] == satellite_tools.FAIL_INVALID


def test_search_and_selection_failures_pass_through_with_their_stage():
    tools = _tools()
    tools._search = lambda provider, target: {"failure": {"reason": stac.FAIL_STAC_UNAVAILABLE, "detail": "down"}}
    assert tools.analyse_area("NDVI", "2023-07-01")["failure"]["reason"] == stac.FAIL_STAC_UNAVAILABLE
    assert tools.compare_change("NDVI", "2019-07-01", "2023-07-01")["stage"] == "before"
    tools = _tools(scenes=lambda provider, target: [_scene("far", "2020-01-01")])
    assert tools.analyse_area("NDVI", "2023-07-01")["failure"]["reason"] == scene_selection.FAIL_NO_WINDOW


def test_thermal_searches_landsat_and_converts_stored_values_to_celsius():
    seen = []
    landsat = _scene("LC08", "2024-07-31", bands=("lwir11",), provider="landsat", scaling={"lwir11": {"scale": 0.00341802, "offset": 149.0}})
    tools = _tools(scenes=lambda provider, target: seen.append(provider) or [landsat])
    raster_source.set_reader(_Reader({"lwir11": [[43000, 43300]]}))
    out = tools.analyse_area("thermal", "2024-07-31")
    assert seen == ["landsat"]
    # DN x 0.00341802 + 149 gives 295.97 K and 296.99 K, a mean of 23.3 C
    assert out["statistics"]["mean"] == pytest.approx(23.3, abs=0.1)
    assert out["map"] == "not drawn"


def test_thermal_refuses_values_that_are_not_kelvin():
    tools = _tools(scenes=lambda provider, target: [_scene("LC08", "2024-07-31", bands=("lwir11",), provider="landsat")])
    raster_source.set_reader(_Reader({"lwir11": [[43000, 43300]]}))
    assert tools.analyse_area("thermal", "2024-07-31")["failure"]["reason"] == satellite_tools.FAIL_NOT_KELVIN


def test_analyse_area_reads_the_winning_scene_once_and_draws_it():
    overlays = []
    reader = _Reader({"nir": [[0.6]], "red": [[0.2]]})
    raster_source.set_reader(reader)
    tools = _tools(overlays, scenes=lambda provider, target: [_scene("cloudy", "2024-08-02", cloud=40), _scene("clear", "2024-08-09", cloud=4)])
    out = tools.analyse_area("NDVI", "2024-08-15")
    assert reader.calls == ["clear"]
    assert out["scene"]["scene_id"] == "clear" and out["scene"]["actual_offset_days"] == -6
    assert out["statistics"]["mean"] == pytest.approx(0.5)
    assert out["area_ha"] > 0 and out["pixel_size_m"] == pytest.approx(10.0, abs=0.5)
    assert len(overlays) == 1 and overlays[0]["legend"]["kind"] == "index"
    json.dumps(out)


def test_injected_band_data_bypasses_the_reader():
    reader = _Reader({})
    raster_source.set_reader(reader)
    tools = _tools(scenes=lambda provider, target: [_scene("s1", target, band_data={"nir": [[0.6, 0.6]], "red": [[0.2, 0.2]]})])
    assert tools.analyse_area("NDVI", "2024-06-15")["statistics"]["mean"] == pytest.approx(0.5)
    assert reader.calls == []


def test_partial_coverage_and_read_failures_surface():
    tools = _tools(scenes=lambda provider, target: [_scene("s", target)])
    raster_source.set_reader(_Reader({"nir": [[0.6]], "red": [[0.2]]}, nodata_fraction=0.5))
    assert raster_source.WARN_PARTIAL_COVERAGE in tools.analyse_area("NDVI", "2024-08-15")["warnings"]
    raster_source.set_reader(_Reader({}, failure={"reason": raster_source.FAIL_READ_FAILED, "detail": "timeout"}))
    assert tools.analyse_area("NDVI", "2024-08-15")["failure"]["reason"] == raster_source.FAIL_READ_FAILED
    assert tools.compare_change("NDVI", "2023-08-15", "2024-08-15")["stage"] == "before"


def test_compare_change_reads_both_winners_and_draws_the_change():
    overlays = []
    reader = _Reader({"nir": [[0.6, 0.6]], "red": [[0.2, 0.4]]})
    raster_source.set_reader(reader)
    tools = _tools(overlays, scenes=lambda provider, target: [_scene(f"clear-{target}", target, cloud=4), _scene(f"cloudy-{target}", target, cloud=30)])
    out = tools.compare_change("NDVI", "2023-08-15", "2024-08-15")
    assert sorted(reader.calls) == ["clear-2023-08-15", "clear-2024-08-15"]
    assert out["before_scene"]["scene_id"] == "clear-2023-08-15" and out["after_scene"]["scene_id"] == "clear-2024-08-15"
    assert out["mean_before"] == out["mean_after"] and out["statistics"]["mean"] == pytest.approx(0.0)
    assert out["seasonal_mismatch"] is False
    assert len(overlays) == 1 and overlays[0]["legend"]["kind"] == "change"
    assert overlays[0]["provenance"]["before"]["scene_id"] == "clear-2023-08-15"
    json.dumps(out)


def test_no_code_runner_is_exposed():
    import geospatial

    names = set(dir(geospatial)) | set(dir(satellite_tools))
    for banned in ("python_repl", "PythonInterpreter", "exec_code", "execute_code"):
        assert banned not in names

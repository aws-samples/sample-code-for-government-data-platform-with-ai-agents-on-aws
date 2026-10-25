"""Builds the geography reference files: council centroids, boundaries and region lookup, the postcode-to-council lookup and the council code history."""
import csv
import io
import json
import logging
import os
import tempfile
import zipfile

import bronze
import fetch

import code_history

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ARCGIS = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
# The May 2025 council boundaries; the field names carry the two-digit year
LAD_SERVICE = "LAD_MAY_2025_UK_BGC_V2"
LAD_REGION_SERVICE = "LAD25_RGN25_EN_LU_v2"
YEAR = "25"
CODE, NAME = f"LAD{YEAR}CD", f"LAD{YEAR}NM"
# The NSPL release on the Open Geography Portal
NSPL_ITEM_ID = "5dd216d9899044348a5b08fee09ac5a4"
PREFIX = "bronze/ons/geography/"
BOUNDARY_PAGE = 50


def _csv(header, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def centroids():
    url = f"{ARCGIS}/{LAD_SERVICE}/FeatureServer/0/query?where=1%3D1&outFields={CODE},{NAME},LAT,LONG&returnGeometry=false&f=json&resultRecordCount=500"
    attrs = [f["attributes"] for f in fetch.get_json(url)["features"]]
    rows = [(a[CODE], (a[NAME] or "").strip(), round(a["LAT"], 6), round(a["LONG"], 6)) for a in attrs if a.get("LAT") is not None and a.get("LONG") is not None]
    return bronze.put(f"{PREFIX}lad-centroids.csv", _csv(["geography_code", "geography_name", "latitude", "longitude"], rows)), len(rows)


def boundaries():
    """Boundary GeoJSON in pages: the endpoint 504s on one all-features request and only pages stably with an explicit sort."""
    features, offset = [], 0
    while True:
        url = (f"{ARCGIS}/{LAD_SERVICE}/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&returnGeometry=true&f=geojson"
               f"&orderByFields={CODE}&resultOffset={offset}&resultRecordCount={BOUNDARY_PAGE}")
        page = fetch.get_json(url, timeout=120)
        features += page.get("features", [])
        if not (page.get("exceededTransferLimit") or page.get("properties", {}).get("exceededTransferLimit")):
            break
        offset += BOUNDARY_PAGE
    for f in features:
        props = f.setdefault("properties", {})
        props["geography_code"], props["geography_name"] = props.get(CODE), props.get(NAME)
    body = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    return bronze.put(f"{PREFIX}lad-boundaries.geojson", body, "application/geo+json"), len(features)


def lad_to_region():
    fields = f"{CODE},{NAME},RGN{YEAR}CD,RGN{YEAR}NM"
    url = f"{ARCGIS}/{LAD_REGION_SERVICE}/FeatureServer/0/query?where=1%3D1&outFields={fields}&returnGeometry=false&f=json&resultRecordCount=500"
    rows = [(a[CODE], (a[NAME] or "").strip(), a[f"RGN{YEAR}CD"], (a[f"RGN{YEAR}NM"] or "").strip()) for a in (f["attributes"] for f in fetch.get_json(url)["features"])]
    return bronze.put(f"{PREFIX}lad-to-region.csv", _csv(["geography_code", "geography_name", "region_code", "region_name"], rows)), len(rows)


def postcode_to_la():
    """Every UK postcode to its council code, from the NSPL zip. 2.7M rows, streamed from the zip into a temp file, never held in memory."""
    count = 0
    with tempfile.TemporaryFile() as zip_tmp, tempfile.TemporaryFile() as out:
        fetch.download(f"https://www.arcgis.com/sharing/rest/content/items/{NSPL_ITEM_ID}/data", zip_tmp, timeout=300)
        zip_tmp.seek(0)
        text_out = io.TextIOWrapper(out, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(text_out)
        writer.writerow(["postcode", "geography_code"])
        with zipfile.ZipFile(zip_tmp) as zf:
            name = next(n for n in zf.namelist() if n.startswith("Data/NSPL") and n.endswith(".csv"))
            with zf.open(name) as f:
                for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                    pc, la = r.get("pcds", "").strip().upper(), r.get("laua", "").strip()
                    if pc and la:
                        writer.writerow([pc, la])
                        count += 1
        text_out.flush()
        text_out.detach()
        return bronze.upload(f"{PREFIX}postcode-to-la.csv", out), count


def la_code_history():
    data, release, count = code_history.build()
    logger.info(json.dumps({"message": "Code History Database release", "release": release}))
    return bronze.put(f"{PREFIX}la-code-history.csv", data), count


def handler(event, context):
    """Every file is attempted; the invocation still fails if any did, which surfaces the stale file."""
    written, failures = {}, []
    for build in (centroids, boundaries, lad_to_region, postcode_to_la, la_code_history):
        try:
            size, count = build()
            written[build.__name__] = {"bytes": size, "count": count}
        except Exception as e:
            logger.exception("%s failed", build.__name__)
            failures.append(f"{build.__name__}: {e}")
    if failures:
        raise RuntimeError(f"Geography reference files not rebuilt: {failures}")
    return bronze.report("geography-reference", files=written)

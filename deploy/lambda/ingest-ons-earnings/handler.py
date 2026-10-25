"""Downloads the latest version of every yearly ASHE (tables 7 and 8) edition to bronze."""
import json
import logging
import os

import bronze
import fetch
import ons

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "ashe-tables-7-and-8"
PREFIX = "bronze/ons/earnings/"


def handler(event, context):
    editions = ons.editions(DATASET)
    # The sweep below would otherwise delete every file in the prefix
    if not editions:
        raise RuntimeError(f"ONS returned no editions for {DATASET}")
    written = []
    for edition in editions:
        version, csv_url = ons.latest_version(DATASET, edition)
        logger.info(json.dumps({"message": "Downloading ONS earnings data", "edition": edition, "version": version, "url": csv_url}))
        key = f"{PREFIX}ashe-7-8-{edition}.csv"
        size = bronze.put(key, fetch.get(csv_url, timeout=300))
        written.append({"edition": edition, "version": version, "s3_key": key, "bytes": size})
    # One file per edition; anything else in the prefix would load as duplicate years
    bronze.sweep(PREFIX, {w["s3_key"] for w in written})
    return bronze.report(DATASET, editions=written)

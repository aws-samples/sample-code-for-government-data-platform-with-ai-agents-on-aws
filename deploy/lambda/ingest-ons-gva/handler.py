"""Downloads the latest version of ONS GVA by industry by local authority to bronze."""
import json
import tempfile
import logging
import os

import bronze
import fetch
import ons

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "gva-by-industry-by-local-authority"
S3_KEY = "bronze/ons/gva/gva-by-industry-by-la.csv"


def handler(event, context):
    version, csv_url = ons.latest_version(DATASET, "time-series")
    logger.info(json.dumps({"message": "Downloading ONS GVA data", "version": version, "url": csv_url}))
    with tempfile.TemporaryFile() as out:
        fetch.download(csv_url, out, timeout=240)
        size = bronze.upload(S3_KEY, out, metadata={"ons-version": str(version)})
    # The Glue job reads the whole prefix; versioned files from earlier runs would load as duplicate rows
    bronze.sweep("bronze/ons/gva/", {S3_KEY})
    return bronze.report(DATASET, S3_KEY, version=version, bytes=size)

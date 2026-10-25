"""Downloads the latest version of ONS personal wellbeing by local authority to bronze."""
import json
import logging
import os

import bronze
import fetch
import ons

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "wellbeing-local-authority"
S3_KEY = "bronze/ons/wellbeing/wellbeing-local-authority.csv"


def handler(event, context):
    version, csv_url = ons.latest_version(DATASET, "time-series")
    logger.info(json.dumps({"message": "Downloading ONS wellbeing data", "version": version, "url": csv_url}))
    size = bronze.put(S3_KEY, fetch.get(csv_url, timeout=60), Metadata={"ons-version": str(version)})
    # The Glue job reads the whole prefix; versioned files from earlier runs would load as duplicate rows
    bronze.sweep("bronze/ons/wellbeing/", {S3_KEY})
    return bronze.report(DATASET, S3_KEY, version=version, bytes=size)

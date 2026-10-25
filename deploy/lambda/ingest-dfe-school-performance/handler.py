"""DfE KS4 school performance by local authority and pupil characteristics, from Explore Education Statistics."""
import json
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API_BASE = "https://api.education.gov.uk/statistics/v1"
DATASET_ID = "b3e19901-5d2b-b676-bb4c-e60937d74725"
PREFIX = "bronze/dfe/school-performance/"


def handler(event, context):
    """The latest version of the dataset from Explore Education Statistics. The API returns gzip, stored as is; silver reads the newest file."""
    version = fetch.get_json(f"{API_BASE}/data-sets/{DATASET_ID}", timeout=30)["latestVersion"]["version"]
    logger.info(json.dumps({"message": "Downloading DfE data", "dataset": DATASET_ID, "version": version}))
    key = f"{PREFIX}ks4-v{version}.csv.gz"
    size = bronze.put(key, fetch.get(f"{API_BASE}/data-sets/{DATASET_ID}/csv?dataSetVersion={version}", timeout=300), ContentEncoding="gzip")
    return bronze.report("ks4-school-performance", key, version=version, bytes=size)

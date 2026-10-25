"""Claimant Count by local authority and month (NOMIS NM_162_1)."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_162_1"
S3_KEY = "bronze/nomis/claimant-count/claimant-count-by-la.csv"
QUERY = f"geography={nomis.TYPE424}&date=latestMINUS200-latest&gender=0&age=0&measure=1&measures=20100&select=date_name,geography_name,geography_code,obs_value"


def handler(event, context):
    rows, size = nomis.fetch_to_s3(DATASET, QUERY, S3_KEY)
    return bronze.report("nomis-claimant-count", S3_KEY, rows=rows, bytes=size)

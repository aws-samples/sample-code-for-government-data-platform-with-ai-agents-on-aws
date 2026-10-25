"""Downloads the MHCLG Revenue Outturn multi-year CSV of local authority spending by service to bronze."""
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CSV_URL = "https://assets.publishing.service.gov.uk/media/6937fe05e447374889cd8f4b/Revenue_Outturn_time_series_data_v3.1.csv"
S3_KEY = "bronze/mhclg/spending/revenue-outturn-time-series.csv"


def handler(event, context):
    data = fetch.get(CSV_URL, timeout=120)
    size = bronze.put(S3_KEY, data)
    return bronze.report("mhclg-spending", S3_KEY, rows=data.count(b"\n") - 1, bytes=size)

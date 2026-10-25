"""Downloads the latest UK House Price Index average prices file, which carries the full back series, to bronze."""
import urllib.error
from datetime import UTC, datetime, timedelta
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BASE_URL = "https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data"
S3_KEY = "bronze/ons/hpi/average-prices-latest.csv"
MONTHS_BACK = 6


def handler(event, context):
    """Walks back month by month until a published file is found; the latest month lags by six to eight weeks."""
    first = datetime.now(UTC).replace(day=1)
    for _ in range(MONTHS_BACK):
        try:
            data = fetch.get(f"{BASE_URL}/Average-prices-{first:%Y-%m}.csv", timeout=60)
            break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            first = (first - timedelta(days=1)).replace(day=1)
    else:
        raise RuntimeError(f"No HPI file for any of the last {MONTHS_BACK} months")

    size = bronze.put(S3_KEY, data)
    return bronze.report("ons-hpi", S3_KEY, year=first.year, month=first.month, bytes=size)

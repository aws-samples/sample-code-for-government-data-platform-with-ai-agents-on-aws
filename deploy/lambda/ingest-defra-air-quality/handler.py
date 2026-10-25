"""Downloads DEFRA's population-weighted annual PM2.5 by local authority, one file a year from 2021, into one bronze CSV."""
import csv
import io
import json
import logging
import os
import urllib.error
from datetime import UTC, datetime

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BASE_URL = "https://uk-air.defra.gov.uk/datastore/pcm"
START_YEAR = 2021
S3_KEY = "bronze/defra/air-quality/pm25-by-local-authority.csv"
COLUMNS = ["calendar_year", "geography_code", "geography_name", "pm25_total", "pm25_non_anthropogenic", "pm25_anthropogenic"]


def _year_rows(year):
    """The rows of one year's file as (year, code, name, total, non-anthropogenic, anthropogenic); none if it isn't published yet."""
    try:
        raw = fetch.get(f"{BASE_URL}/popwmpm25{year}byUKlocalauthority.csv").decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # The current year's file appears each October
        if e.code != 404:
            raise
        logger.warning(json.dumps({"message": "Skipping year, not published", "year": year}))
        return []
    lines = raw.strip().splitlines()
    if len(lines) < 5:
        raise RuntimeError(f"DEFRA PM2.5 file for {year} has {len(lines)} lines, expected metadata rows, a header and data")
    # Four metadata and header rows, then code, total, non-anthropogenic, anthropogenic, name
    return [(year, r[0].strip(), r[4].strip(), r[1].strip(), r[2].strip(), r[3].strip()) for r in csv.reader(lines[4:]) if len(r) >= 5 and r[0].strip()]


def handler(event, context):
    end_year = datetime.now(UTC).year
    rows = [row for year in range(START_YEAR, end_year + 1) for row in _year_rows(year)]
    if not rows:
        raise RuntimeError(f"No DEFRA PM2.5 files found for {START_YEAR} to {end_year}")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    size = bronze.put(S3_KEY, out.getvalue().encode())
    return bronze.report("defra-air-quality", S3_KEY, rows=len(rows), bytes=size, years=f"{START_YEAR}-{end_year}")

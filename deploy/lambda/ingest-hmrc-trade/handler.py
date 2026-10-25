"""HMRC Regional Trade Statistics from 2018 and the region, country and flow type lookups, from the UK Trade Info API."""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API_BASE = "https://api.uktradeinfo.com"
# The API allows 60 requests a minute
RATE_LIMIT_PAUSE = 1.1
FIRST_YEAR = 2018
PREFIX = "bronze/hmrc/trade/"
RTS_PREFIX = f"{PREFIX}rts/"
# Pages land here first and move to RTS_PREFIX only when every year succeeded, which keeps silver from reading a half-written run
STAGING_PREFIX = f"{PREFIX}rts-staging/"
REFERENCE = {"regions": "Region", "countries": "Country", "flow-types": "FlowType"}


class RateLimiter:
    """Spaces request starts RATE_LIMIT_PAUSE apart across all threads."""

    def __init__(self, pause):
        self.pause, self.next_at, self.lock = pause, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)  # nosemgrep: arbitrary-sleep, rate limit
            self.next_at = time.monotonic() + self.pause


limiter = RateLimiter(RATE_LIMIT_PAUSE)


def _get(url):
    limiter.wait()
    return fetch.get_json(url, timeout=120).get("value", [])


def _fetch_year(year):
    """Page one year of RTS with $skip until a page comes back empty, writing each page to staging. Returns (keys, rows)."""
    keys, rows, skip = [], 0, 0
    while True:
        # The API serves at most 30,000 rows a request and treats $top as a total, hence paging with $skip alone
        records = _get(f"{API_BASE}/RTS?%24filter=MonthId%20ge%20{year}01%20and%20MonthId%20le%20{year}12&%24skip={skip}")
        if not records:
            return keys, rows
        rows += len(records)
        skip += len(records)
        key = f"{STAGING_PREFIX}page-{year}-{len(keys):03d}.json"
        bronze.put(key, json.dumps(records).encode(), "application/json")
        keys.append(key)
        logger.info(json.dumps({"message": "Wrote RTS page", "key": key, "records": len(records), "year_so_far": rows}))


def _publish(staged):
    """Copy the staged pages over RTS_PREFIX, delete pages this run didn't write, then clear staging."""
    published = set()
    for key in staged:
        target = RTS_PREFIX + key[len(STAGING_PREFIX):]
        bronze.s3.copy_object(Bucket=bronze.BUCKET, CopySource={"Bucket": bronze.BUCKET, "Key": key}, Key=target, ContentType="application/json", MetadataDirective="REPLACE")
        published.add(target)
    stale = bronze.sweep(RTS_PREFIX, published)
    bronze.delete(staged)
    logger.info(json.dumps({"message": "Published RTS pages", "pages": len(published), "stale_deleted": len(stale)}))


def handler(event, context):
    ref_keys = []
    for name, endpoint in REFERENCE.items():
        key = f"{PREFIX}{name}.json"
        bronze.put(key, json.dumps(_get(f"{API_BASE}/{endpoint}"), indent=2).encode(), "application/json")
        ref_keys.append(key)

    # One thread a year: a request takes several seconds and one year at a time doesn't fit in the Lambda's 15 minutes
    years = range(FIRST_YEAR, datetime.now(UTC).year + 1)
    bronze.delete(bronze.list_keys(STAGING_PREFIX))
    with ThreadPoolExecutor(max_workers=len(years)) as pool:
        results = list(pool.map(_fetch_year, years))
    _publish([k for keys, _ in results for k in keys])
    return bronze.report("hmrc-trade", s3_keys=[RTS_PREFIX] + ref_keys, rts_count=sum(rows for _, rows in results))

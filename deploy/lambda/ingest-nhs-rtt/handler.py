"""Downloads the monthly NHS England RTT waiting times zips, found by scraping the yearly data pages because the URLs carry random hashes."""
import gzip
import io
import json
import logging
import os
import re
import urllib.error
import zipfile
from datetime import UTC, datetime
from html.parser import HTMLParser

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

PAGE_BASE = "https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/rtt-data"
FINANCIAL_YEARS = 3
PREFIX = "bronze/nhs/rtt-waiting-times/"
MONTH_TAG = re.compile(r"Full-CSV-data-file-(\w+\d{2})-", re.IGNORECASE)


class _ZipLinks(HTMLParser):
    """The href of every <a> to a Full CSV zip."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "") if tag == "a" else ""
        if href.lower().endswith(".zip") and "full-csv" in href.lower():
            self.urls.append(href if href.startswith("http") else f"https://www.england.nhs.uk{href}")


def _year_pages():
    """The yearly data pages for the current financial year and the two before it."""
    now = datetime.now(UTC)
    fy_start = now.year if now.month >= 4 else now.year - 1
    return [f"{PAGE_BASE}-{fy}-{str(fy + 1)[-2:]}" for fy in range(fy_start, fy_start - FINANCIAL_YEARS, -1)]


def _zip_urls(page_url):
    """The Full CSV zip links on a yearly page; none if the page isn't published yet."""
    try:
        html = fetch.get(page_url, timeout=120).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return []
    parser = _ZipLinks()
    parser.feed(html)
    logger.info(json.dumps({"message": "Scraped RTT page", "page": page_url, "zips": len(parser.urls)}))
    return parser.urls


def handler(event, context):
    pages = _year_pages()
    # One zip per month tag; a revised file appears under a new URL with the same tag
    zips = {}
    for url in (u for page in pages for u in _zip_urls(page)):
        if (m := MONTH_TAG.search(url)) and m.group(1) not in zips:
            zips[m.group(1)] = url
    if not zips:
        raise RuntimeError(f"No Full CSV zip links found on the RTT pages {pages}")

    results, failed = [], []
    for tag, url in zips.items():
        logger.info(json.dumps({"message": "Downloading RTT month", "month": tag, "url": url}))
        try:
            with zipfile.ZipFile(io.BytesIO(fetch.get(url, timeout=180))) as zf:
                csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                content = zf.read(csv_name)
        except (urllib.error.HTTPError, zipfile.BadZipFile, StopIteration) as e:
            failed.append(f"{tag}: {e}")
            continue
        key = f"{PREFIX}rtt-{tag.lower()}.csv.gz"
        size = bronze.put(key, gzip.compress(content), ContentEncoding="gzip")
        results.append({"month": tag, "s3_key": key, "rows": content.count(b"\n"), "compressed_bytes": size})

    # Every month is attempted; the run still fails, which surfaces the missing month
    if failed:
        raise RuntimeError(f"RTT months not written: {failed}")
    return bronze.report("nhs-rtt-waiting-times", months_ingested=len(results), results=results)

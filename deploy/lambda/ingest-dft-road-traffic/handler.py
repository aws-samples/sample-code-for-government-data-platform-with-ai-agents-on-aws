"""Downloads DfT road traffic by local authority and the local authority lookup to bronze."""
import json
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API_BASE = "https://roadtraffic.dft.gov.uk/api"
PAGE_SIZE = 100
PREFIX = "bronze/dft/road-traffic/"


def _all_pages(endpoint):
    records, page = [], 1
    while True:
        result = fetch.get_json(f"{API_BASE}/{endpoint}?page[size]={PAGE_SIZE}&page[number]={page}")
        records += result.get("data", [])
        if not result.get("next_page_url"):
            return records
        page += 1


def handler(event, context):
    datasets = {"local-authorities": fetch.get_json(f"{API_BASE}/local-authorities"), "local-authority-traffic": _all_pages("local-authority-traffic")}
    counts = {}
    for name, data in datasets.items():
        bronze.put(f"{PREFIX}{name}.json", json.dumps(data, indent=2).encode(), "application/json")
        counts[name] = len(data)
    return bronze.report("dft-road-traffic", s3_keys=[f"{PREFIX}{n}.json" for n in datasets], counts=counts)

"""Lists every police force and recent month, for the crime Step Function to fan out one download per pair."""
import json
import logging
import os

import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API_BASE = "https://data.police.uk/api"
MONTHS = int(os.environ.get("MONTHS_TO_FETCH", "12"))


def handler(event, context):
    forces = [f["id"] for f in fetch.get_json(f"{API_BASE}/forces", timeout=10)]
    dates = [d["date"] for d in fetch.get_json(f"{API_BASE}/crimes-street-dates", timeout=10)[:MONTHS]]
    logger.info(json.dumps({"message": "Police forces and months", "forces": len(forces), "months": len(dates)}))
    return {"tasks": [{"force": f, "date": d} for d in dates for f in forces]}

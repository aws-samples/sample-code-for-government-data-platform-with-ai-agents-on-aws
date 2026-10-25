"""Downloads street-level crime for one police force and month from the Police API to bronze as JSONL."""
import json
import logging
import os
import urllib.error
import urllib.parse

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API_BASE = "https://data.police.uk/api"


def _crimes(force, neighbourhood_id, date):
    """Crimes inside the neighbourhood's boundary polygon for the month; a neighbourhood with no boundary (404) has none."""
    try:
        boundary = fetch.get_json(f"{API_BASE}/{force}/{neighbourhood_id}/boundary", timeout=10)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    if not boundary:
        return []
    # POST avoids URL length limits with complex polygons
    poly = ":".join(f"{p['latitude']},{p['longitude']}" for p in boundary)
    data = urllib.parse.urlencode({"poly": poly, "date": date}).encode()
    with fetch.request(f"{API_BASE}/crimes-street/all-crime", timeout=60, data=data, method="POST") as resp:
        return json.loads(resp.read())


def handler(event, context):
    """event: {"force": "<id>", "date": "YYYY-MM"}; date defaults to the latest month the API has."""
    force = event["force"]
    date = event.get("date") or fetch.get_json(f"{API_BASE}/crimes-street-dates", timeout=10)[0]["date"]
    neighbourhoods = fetch.get_json(f"{API_BASE}/{force}/neighbourhoods", timeout=30)
    logger.info(json.dumps({"message": "Fetching crimes", "force": force, "date": date, "neighbourhoods": len(neighbourhoods)}))

    crimes = [c for n in neighbourhoods for c in _crimes(force, n["id"], date)]
    if not crimes:
        logger.info(json.dumps({"message": "No crimes found", "force": force, "date": date}))
        return {"statusCode": 200, "dataset": "police-crime", "force": force, "date": date, "records": 0}

    year, month = date.split("-")
    key = f"bronze/police/crime/year={year}/month={month}/force={force}.jsonl"
    size = bronze.put(key, "\n".join(json.dumps(c) for c in crimes).encode(), "application/x-ndjson")
    return bronze.report("police-crime", key, force=force, date=date, records=len(crimes), bytes=size)

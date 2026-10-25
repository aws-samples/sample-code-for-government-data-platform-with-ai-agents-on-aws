"""DWP Stat-Xplore REST API (https://stat-xplore.dwp.gov.uk/webapi/rest/v1): API key, valueset paging, table queries, cube to rows."""
import gzip
import json
import logging
import os
import re
import urllib.parse

import boto3
import fetch

logger = logging.getLogger()

API_BASE = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


def api_key():
    """The dwp_stat_xplore key from the API keys secret."""
    secret_id = os.environ["API_KEYS_SECRET_ID"]
    key = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]).get("dwp_stat_xplore", "")
    if not key or key == "REPLACE_ME":
        raise RuntimeError(f"DWP Stat-Xplore API key not set in {secret_id}: see step 7 of the README")
    return key


def request(key, url, body=None, timeout=240):
    """GET, or POST when body is given. Returns (parsed JSON, response headers)."""
    headers = {"APIKey": key, "Accept-Encoding": "gzip"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    with fetch.request(url, timeout, headers, data=data, method="POST" if data else "GET") as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw), resp.headers


def value_ids(key, valueset):
    """Every value id in a valueset, following the Link rel="next" pages."""
    ids = []
    url = f"{API_BASE}/schema/{urllib.parse.quote(valueset, safe='')}"
    while url:
        data, headers = request(key, url, timeout=120)
        ids.extend(child["id"] for child in data.get("children", []) if child.get("type") == "VALUE")
        match = _NEXT_LINK.search(headers.get("link", ""))
        url = match.group(1) if match else None
    logger.info(json.dumps({"message": "Fetched valueset", "valueset": valueset.split(":")[-1], "values": len(ids)}))
    return ids


def table(key, database, measure, geo_field, geo_ids, date_field, date_ids=None):
    """Query a table by geography and date, recoding each dimension to the given value ids."""
    recodes = {geo_field: {"map": [[g] for g in geo_ids], "total": False}}
    if date_ids:
        recodes[date_field] = {"map": [[d] for d in date_ids], "total": False}
    query = {"database": database, "measures": [measure], "dimensions": [[geo_field], [date_field]], "recodes": recodes}
    result, _ = request(key, f"{API_BASE}/table", query, timeout=300)
    return result


def rows(result):
    """(geography_code, name, date_label, date_uri_suffix, count) for every cell with a value, geography then date."""
    geo_field, date_field = result["fields"]
    values = next(iter(result["cubes"].values()))["values"]
    for i, geo in enumerate(geo_field["items"]):
        code, name = geo["uris"][0].split(":")[-1], geo["labels"][0]
        for j, date in enumerate(date_field["items"]):
            if values[i][j] is not None:
                yield code, name, date["labels"][0], date["uris"][0].split(":")[-1], int(values[i][j])

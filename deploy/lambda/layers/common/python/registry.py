"""The data source registry for the gateway Lambdas: a cached scan, the sources behind a set of warehouse tables, and their attribution statements."""
import logging
import os
import re
import time
from datetime import date

import boto3

logger = logging.getLogger()

TABLE_NAME = os.environ.get("DATA_SOURCE_REGISTRY_TABLE", "")
CACHE_SECONDS = 3600
_cache = {"items": [], "at": 0.0}
_SELECT_RE = re.compile(r"\bSELECT\s+(.*?)\bFROM\b", re.IGNORECASE | re.DOTALL)


def items():
    """Every registry item, re-read at most once an hour per container."""
    if not TABLE_NAME:
        return []
    if time.time() - _cache["at"] > CACHE_SECONDS:
        table = boto3.resource("dynamodb").Table(TABLE_NAME)
        found, kwargs = [], {}
        while True:
            resp = table.scan(**kwargs)
            found += resp.get("Items", [])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        _cache.update(items=found, at=time.time())
    return _cache["items"]


def sources_for(tables, sql=None):
    """Registry items whose gold tables are in `tables`; for an mv_* view, the sources of the columns `sql` selects, or all of its sources without `sql`."""
    tables = {t.lower() for t in tables}
    select = m.group(1) if sql and (m := _SELECT_RE.search(sql)) else "*"
    matched = []
    for item in items():
        if tables & {t.lower() for t in item.get("gold_tables", [])}:
            matched.append(item)
            continue
        for view, columns in item.get("view_columns", {}).items():
            if view.lower() in tables and (select.strip() == "*" or any(re.search(rf"\b{c}\b", select, re.IGNORECASE) for c in columns)):
                matched.append(item)
                break
    return matched


def fill_year(statement):
    return statement.replace("{year}", str(date.today().year))


def statements(sources):
    """The unique attribution statements of `sources`, with the year filled in."""
    out = []
    for item in sources:
        for s in item.get("attribution", []):
            if fill_year(s) not in out:
                out.append(fill_year(s))
    return out

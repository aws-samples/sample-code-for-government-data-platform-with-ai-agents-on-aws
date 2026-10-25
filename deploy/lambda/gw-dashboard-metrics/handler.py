"""GET /metrics for the usage dashboard: question counts, coverage and live agent state, polled every 15 seconds by the dashboard container."""
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
tracking = dynamodb.Table(os.environ["DATASET_TRACKING_TABLE"])
registry = dynamodb.Table(os.environ["DATA_SOURCE_REGISTRY_TABLE"])
live = dynamodb.Table(os.environ["DASHBOARD_LIVE_TABLE"])
shared_answers = dynamodb.Table(os.environ["SHARED_ANSWERS_TABLE"])

AGENTS = ("main", "geospatial", "walkthrough")
LOCAL_AUTHORITIES = 331
# The registry changes once a day at most; this is polled every 15 seconds
REGISTRY_TTL = 300
_registry = {"items": None, "loaded_at": 0.0}


def _scan(table, **kwargs):
    while True:
        resp = table.scan(**kwargs)
        yield from resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _registry_items():
    if _registry["items"] is None or time.monotonic() - _registry["loaded_at"] > REGISTRY_TTL:
        _registry.update(items=list(_scan(registry)), loaded_at=time.monotonic())
    return _registry["items"]


def _question_counts():
    """(distinct questions, distinct questions today, SQL queries) from the tracking table, one row per table a query read."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    queries, queries_today, rows = set(), set(), 0
    for item in _scan(tracking, ProjectionExpression="query_id, queried_at"):
        rows += 1
        queries.add(item["query_id"])
        if item.get("queried_at", 0) >= today:
            queries_today.add(item["query_id"])
    return len(queries), len(queries_today), rows


def _coverage():
    items = _registry_items()
    return {
        "data_sources": len(items),
        "government_departments": len({i["department"] for i in items if i.get("department")}),
        "total_rows": sum(int(i.get("row_count", 0)) for i in items),
        "local_authorities": LOCAL_AUTHORITIES,
    }


def _last_datasources(query_id):
    """Friendly source names for the tables the last question read, falling back to the table names."""
    if not query_id:
        return []
    tables = sorted({i["table_name"] for i in tracking.query(KeyConditionExpression="query_id = :q", ExpressionAttributeValues={":q": query_id}, ProjectionExpression="table_name")["Items"]})
    names = {gt: item.get("name", item["source_id"]) for item in _registry_items() for gt in item.get("gold_tables", [])}
    friendly = list(dict.fromkeys(names[t] for t in tables if t in names))
    return friendly or tables[:5]


def _live():
    state = {pk: live.get_item(Key={"pk": pk}).get("Item", {}) for pk in AGENTS}
    main, geo, walkthrough = state["main"], state["geospatial"], state["walkthrough"]
    return {
        "last_question": main.get("last_question", ""),
        "last_question_time": main.get("last_question_time", ""),
        "last_datasources": _last_datasources(main.get("query_id", "")),
        "last_area": geo.get("last_area", ""),
        "areas_explored": int(geo.get("areas_explored", 0)),
        "walkthroughs": int(walkthrough.get("walkthroughs", 0)),
        "agent_status": "responding" if any(s.get("agent_status") == "responding" for s in state.values()) else "idle",
        "last_response_ms": int(main.get("last_response_ms", 0)),
    }


def _latest_chart():
    """The last chart of the most recently shared answer, or None."""
    answers = [a for a in _scan(shared_answers, ProjectionExpression="charts, created_at", FilterExpression=Attr("charts").exists()) if a.get("charts") and a["charts"] != "[]"]
    if not answers:
        return None
    charts = max(answers, key=lambda a: a.get("created_at", ""))["charts"]
    charts = json.loads(charts) if isinstance(charts, str) else charts
    return charts[-1] if charts else None


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError


def handler(event, context):
    try:
        total, today, sql_queries = _question_counts()
        live_state = _live()
        body = {
            "platform": "govdata",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metrics": {
                "total_questions_asked": total,
                "questions_today": today,
                "sql_queries_executed": sql_queries,
                "areas_explored": live_state["areas_explored"],
                "walkthroughs": live_state["walkthroughs"],
            },
            "live": live_state,
            "latest_chart": _latest_chart(),
            "coverage": _coverage(),
        }
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, default=_decimal_default)}
    except Exception:
        logger.exception("Dashboard metrics error")
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Metrics unavailable"})}

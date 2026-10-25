"""AgentCore Gateway tool query_data: a read-only SQL query against the Redshift gold layer, with the attribution the sources it read are owed."""
import logging
import os
import re
import time

import boto3
import redshift_data
import registry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TRACKING_TABLE = os.environ["DATASET_TRACKING_TABLE"]
MAX_ROWS = 500

_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+(?:gold\.)?(\w+)", re.IGNORECASE)


def _tables(sql):
    return {t.lower() for t in _TABLE_RE.findall(sql) if t.lower().startswith(("rs_", "mv_", "fact_", "dim_"))}


def _track_tables(query_id, tables):
    """Record which warehouse tables the query read, for the usage dashboard; a failure here never fails the query."""
    if not tables:
        return
    try:
        ts = int(time.time())
        with dynamodb.Table(TRACKING_TABLE).batch_writer() as batch:
            for t in tables:
                batch.put_item(Item={"query_id": query_id, "table_name": t, "queried_at": ts, "ttl": ts + 86400 * 30})
    except Exception:
        logger.exception("Failed to track tables for %s", query_id)


def _attribution(tables, sql):
    """Statements for the sources behind `tables`; a registry failure never fails the query."""
    try:
        return registry.statements(registry.sources_for(tables, sql))
    except Exception:
        logger.exception("Failed to read the registry for attribution")
        return []


def handler(event, context):
    arguments = event.get("arguments", event)
    sql = str(arguments.get("sql", "")).strip()
    if not sql:
        return {"error": "Missing required parameter: sql"}
    if violation := redshift_data.read_only_violation(sql):
        return {"error": violation}

    try:
        columns, rows = redshift_data.run(sql, context, max_rows=MAX_ROWS)
    except redshift_data.QueryError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("query_data failed")
        return {"error": "The query could not be run. Check the SQL against describe_schema and try again."}

    tables = _tables(sql)
    _track_tables(context.aws_request_id, tables)
    truncated = len(rows) > MAX_ROWS
    return {
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": min(len(rows), MAX_ROWS),
        "truncated": truncated,
        "attribution": _attribution(tables, sql),
    }

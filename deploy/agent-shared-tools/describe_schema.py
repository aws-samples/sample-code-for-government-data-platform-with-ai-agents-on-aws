"""Describes the rs_* tables and mv_* views in the warehouse, cached for an hour because the ETL rebuilds them daily."""
import time
import json
import logging
from strands import tool

from . import run_sql

logger = logging.getLogger(__name__)

CACHE_SECONDS = 3600
_schema_cache: dict | None = None
_cached_at = 0.0

_ALL_SQL = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND (table_name LIKE 'rs\\_%' OR table_name LIKE 'mv\\_%')
    ORDER BY 1, 2
"""
_ONE_SQL = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table_name
    ORDER BY 1, 2
"""


def _query(sql, parameters=None):
    result = run_sql.execute_and_track(sql, parameters=parameters, timeout=60, max_rows=None)
    if "error" in result:
        raise RuntimeError(result["error"])
    schema: dict[str, list] = {}
    for row in result["rows"]:
        schema.setdefault(row["table_name"], []).append({"name": row["column_name"], "type": row["data_type"]})
    return schema


@tool
def describe_schema(table_name: str = "") -> str:
    """Describe available tables, views, and columns in the data warehouse.

    Returns table/view names, column names, and data types. Call with no arguments
    to get the full schema, or pass a table_name to get columns for just that table.

    Args:
        table_name: Optional, a single rs_* table or mv_* view (e.g. "rs_fact_earnings").
    """
    global _schema_cache, _cached_at
    try:
        if _schema_cache is None or time.time() - _cached_at > CACHE_SECONDS:
            _schema_cache = _query(_ALL_SQL)
            _cached_at = time.time()
            logger.info("Cached schema (%d tables)", len(_schema_cache))
        if not table_name:
            return json.dumps(_schema_cache)
        if table_name in _schema_cache:
            return json.dumps({table_name: _schema_cache[table_name]})
        return json.dumps(_query(_ONE_SQL, {"table_name": table_name}))
    except Exception as e:
        return f"Error describing schema: {e}"

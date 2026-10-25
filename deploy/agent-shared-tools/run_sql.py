"""Runs read-only SQL against the Redshift warehouse through the Data API and records which sources each query touched."""
import os
import re
import time
import json
import logging
import boto3
from strands import tool

logger = logging.getLogger(__name__)

redshift_data = boto3.client("redshift-data")
dynamodb = boto3.resource("dynamodb")

WORKGROUP = os.environ["REDSHIFT_WORKGROUP"]
DATABASE = os.environ.get("REDSHIFT_DATABASE", "analytics")
TRACKING_TABLE = os.environ.get("DATASET_TRACKING_TABLE", "")
REGISTRY_TABLE_NAME = os.environ.get("DATA_SOURCE_REGISTRY_TABLE", "")
MAX_ROWS = 500
REGISTRY_CACHE_SECONDS = 3600

_current_query_id = ""


def set_query_id(query_id: str):
    global _current_query_id
    _current_query_id = query_id


_TABLE_RE = re.compile(r"\bgold\.(\w+)", re.IGNORECASE)
# Unqualified names that count as a gold source for the datasets-used panel
_KNOWN_TABLES = {
    "fact_crime", "fact_population", "fact_wellbeing", "fact_earnings",
    "fact_school_performance", "fact_school_detail", "fact_house_prices",
    "fact_claimant_count", "fact_employment", "fact_deprivation",
    "fact_universal_credit", "fact_road_traffic", "fact_aps", "fact_gva",
    "fact_trade", "nhs_rtt_waiting_times",
    "dim_geography", "dim_time", "dim_region_mapping",
    "rs_dim_geography", "rs_dim_time",
    "rs_dim_region_mapping",
    "rs_fact_crime", "rs_fact_population", "rs_fact_wellbeing", "rs_fact_earnings",
    "rs_fact_school_performance", "rs_fact_school_detail", "rs_fact_house_prices",
    "rs_fact_claimant_count", "rs_fact_employment",
    "rs_fact_deprivation", "rs_fact_universal_credit",
    "rs_fact_road_traffic",
    "rs_fact_aps",
    "rs_fact_gva",
    "rs_fact_trade",
    "rs_fact_nhs_rtt",
    "rs_fact_hpi",
    "fact_hpi",
    "rs_fact_nhs_ods",
    "fact_nhs_ods",
    "rs_fact_air_quality",
    "fact_air_quality",
    "rs_fact_la_spending",
    "fact_la_spending",
    "rs_fact_jobs_density",
    "fact_jobs_density",
    "rs_fact_business_counts",
    "fact_business_counts",
    "rs_fact_births_deaths",
    "fact_births_deaths",
    "rs_fact_housing_benefit",
    "fact_housing_benefit",
    "rs_fact_children_low_income",
    "fact_children_low_income",
    "rs_fact_pip",
    "fact_pip",
    "mv_area_overview", "mv_area_timeseries", "mv_uk_summary",
}
_UNQUALIFIED_RE = re.compile(r"\b(?:FROM|JOIN)\s+(\w+(?:\s+(?:AS\s+)?\w+)?(?:\s*,\s*\w+(?:\s+(?:AS\s+)?\w+)?)*)", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|INTO|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|COPY|UNLOAD|CALL|EXECUTE|VACUUM|ANALYZE"
    r"|SET|BEGIN|COMMIT|ROLLBACK|PG_TERMINATE_BACKEND|PG_CANCEL_BACKEND)\b", re.IGNORECASE)
_HIDDEN_SCHEMAS = re.compile(r"\b(gold\.|pg_|stl_|stv_|svv_|svl_|sys_|information_schema\.)", re.IGNORECASE)


def read_only_violation(sql: str) -> str | None:
    """Why sql is not a single read-only SELECT on the serving tables, or None. Comments, string literals and quoted identifiers are blanked first."""
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    text = re.sub(r"'(?:[^']|'')*'", "''", text)
    text = re.sub(r'"[^"]*"', '""', text)
    text = text.strip().rstrip(";").strip()
    if ";" in text:
        return "One statement at a time."
    if not re.match(r"(SELECT|WITH)\b", text, re.IGNORECASE):
        return "Only SELECT queries are allowed."
    if m := _FORBIDDEN.search(text):
        return f"{m.group(1).upper()} is not allowed in a read-only query."
    if m := _HIDDEN_SCHEMAS.search(text):
        return f"{m.group(1)} objects are not available; query the rs_* tables and mv_* views."
    return None


_view_column_sources: dict[str, dict[str, str]] = {}
_all_fact_tables: list[str] = []
_registry_loaded_at = 0.0


def _load_view_column_sources():
    """Map each mv_* view column to the fact table that provides it, from the data source registry."""
    global _view_column_sources, _all_fact_tables, _registry_loaded_at
    _registry_loaded_at = time.time()
    if not REGISTRY_TABLE_NAME:
        return
    try:
        table = dynamodb.Table(REGISTRY_TABLE_NAME)
        items, kwargs = [], {}
        while True:
            resp = table.scan(**kwargs)
            items += resp.get("Items", [])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        mapping: dict[str, dict[str, str]] = {}
        facts: set[str] = set()
        for item in items:
            gold_tables = item.get("gold_tables", [])
            if not gold_tables:
                continue
            fact_table = gold_tables[0]
            facts.add(fact_table)
            for view_name, columns in item.get("view_columns", {}).items():
                for col in columns:
                    mapping.setdefault(view_name, {})[col] = fact_table
        _view_column_sources = mapping
        _all_fact_tables = sorted(facts)
        logger.info("Loaded view column sources: %d views, %d fact tables", len(mapping), len(facts))
    except Exception as e:
        logger.warning("Failed to load view column sources from registry: %s", e)


def _ensure_registry_loaded():
    if time.time() - _registry_loaded_at > REGISTRY_CACHE_SECONDS:
        _load_view_column_sources()


_SELECT_COLS_RE = re.compile(r"\bSELECT\s+(.*?)\bFROM\b", re.IGNORECASE | re.DOTALL)


def _resolve_view_columns(sql: str, tables: set[str]) -> set[str]:
    """Replace a cross-dataset view with the fact tables behind the columns the query selects."""
    _ensure_registry_loaded()
    view_tables = tables & set(_view_column_sources.keys())
    if not view_tables:
        return tables
    m = _SELECT_COLS_RE.search(sql)
    if not m:
        return tables
    select_clause = m.group(1).strip()
    resolved = set()
    for view in view_tables:
        col_map = _view_column_sources[view]
        if select_clause == "*":
            resolved.update(col_map.values())
        else:
            matched = {col_map[c] for c in col_map if re.search(r'\b' + c + r'\b', select_clause)}
            resolved.update(matched or col_map.values())
    resolved.update(tables - view_tables)
    return resolved


def _extract_tables(sql: str) -> list[str]:
    """Gold table and view names a query reads, as the datasets-used panel should credit them."""
    tables = set(_TABLE_RE.findall(sql.lower()))
    for match in _UNQUALIFIED_RE.findall(sql.lower()):
        for part in re.split(r"\s*,\s*", match):
            name = part.split()[0]
            if name in _KNOWN_TABLES:
                tables.add(name)
    tables = _resolve_view_columns(sql.lower(), tables)
    return list(tables)


def _track_tables(query_id: str, tables: list[str]):
    if not TRACKING_TABLE or not query_id or not tables:
        return
    try:
        table = dynamodb.Table(TRACKING_TABLE)
        ts = int(time.time())
        with table.batch_writer() as batch:
            for t in tables:
                batch.put_item(Item={"query_id": query_id, "table_name": t, "queried_at": ts, "ttl": ts + 86400 * 30})
        logger.info("Tracked %d tables for query %s", len(tables), query_id[:8])
    except Exception as e:
        logger.warning("Failed to track tables in DynamoDB: %s", e)


def execute_and_track(sql: str, *, parameters: dict | None = None, timeout: int = 120, max_rows: int | None = MAX_ROWS) -> dict:
    """Run one statement, record the tables it read, and return {'columns', 'rows', 'truncated'} or {'error'}.

    parameters are bound server-side to :name placeholders. The statement is cancelled when the timeout passes or polling fails.
    """
    stmt_id = None
    try:
        kwargs = {"WorkgroupName": WORKGROUP, "Database": DATABASE, "Sql": sql.strip()}
        if parameters:
            kwargs["Parameters"] = [{"name": k, "value": str(v)} for k, v in parameters.items()]
        stmt_id = redshift_data.execute_statement(**kwargs)["Id"]
        deadline = time.monotonic() + timeout
        while True:
            status = redshift_data.describe_statement(Id=stmt_id)
            state = status["Status"]
            if state == "FINISHED":
                break
            if state in ("FAILED", "ABORTED"):
                return {"error": status.get("Error", "Query failed")}
            if time.monotonic() > deadline:
                redshift_data.cancel_statement(Id=stmt_id)
                return {"error": "Query timed out"}
            time.sleep(0.5)  # nosemgrep: arbitrary-sleep, polling Redshift Data API async query

        tables = _extract_tables(sql)
        if tables and _current_query_id:
            _track_tables(_current_query_id, tables)

        columns, rows, token = [], [], None
        while True:
            page = redshift_data.get_statement_result(Id=stmt_id, **({"NextToken": token} if token else {}))
            columns = columns or [c["name"] for c in page["ColumnMetadata"]]
            rows += [{columns[i]: (None if f.get("isNull") else next(iter(f.values()))) for i, f in enumerate(record)} for record in page["Records"]]
            token = page.get("NextToken")
            if not token or (max_rows is not None and len(rows) > max_rows):
                break
        truncated = max_rows is not None and len(rows) > max_rows
        return {"columns": columns, "rows": rows[:max_rows] if truncated else rows, "truncated": truncated}

    except Exception as e:
        if stmt_id:
            try:
                redshift_data.cancel_statement(Id=stmt_id)
            except Exception:
                pass
        return {"error": str(e)}


@tool
def run_sql(sql: str) -> str:
    """Execute a read-only SQL query against the Redshift data warehouse. Results are capped at 500 rows; aggregate or add LIMIT for more.

    Args:
        sql: A SELECT or WITH query to execute.
    """
    if violation := read_only_violation(sql):
        return f"Error: {violation}"
    result = execute_and_track(sql)
    if "error" in result:
        if "timed out" in str(result["error"]).lower():
            return "Query timed out after 120 seconds. The data warehouse may be warming up, try again."
        return f"Query failed: {result['error']}"
    out = {"columns": result["columns"], "rows": result["rows"], "row_count": len(result["rows"])}
    if result["truncated"]:
        out["truncated"] = f"Only the first {MAX_ROWS} rows are shown; aggregate or add a LIMIT."
    return json.dumps(out)

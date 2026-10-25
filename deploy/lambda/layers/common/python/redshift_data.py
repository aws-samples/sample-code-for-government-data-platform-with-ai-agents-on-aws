"""Redshift Data API runner shared by the gateway Lambdas: one statement, polled against the Lambda deadline, cancelled if it runs over."""
import logging
import os
import re
import time

import boto3

client = boto3.client("redshift-data")
logger = logging.getLogger()

WORKGROUP = os.environ["REDSHIFT_WORKGROUP"]
DATABASE = os.environ.get("REDSHIFT_DATABASE", "analytics")
# Seconds kept back from the Lambda deadline for the cancel and the error response
DEADLINE_MARGIN = 10

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|INTO|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|COPY|UNLOAD|CALL|EXECUTE|VACUUM|ANALYZE"
    r"|SET|BEGIN|COMMIT|ROLLBACK|PG_TERMINATE_BACKEND|PG_CANCEL_BACKEND)\b", re.IGNORECASE)
_HIDDEN_SCHEMAS = re.compile(r"\b(gold\.|pg_|stl_|stv_|svv_|svl_|sys_|information_schema\.)", re.IGNORECASE)


class QueryError(Exception):
    """A statement the warehouse rejected, or one that ran out of time."""


def read_only_violation(sql):
    """Why sql is not a single read-only SELECT, or None. Comments, string literals and quoted identifiers are blanked first."""
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


def run(sql, context, parameters=None, max_rows=None):
    """Run one statement and return (columns, rows), each row a dict with None for SQL nulls. Raises QueryError.

    With max_rows, result pages stop being fetched once that many rows are in hand; the caller truncates.
    """
    kwargs = {"WorkgroupName": WORKGROUP, "Database": DATABASE, "Sql": sql.strip()}
    if parameters:
        kwargs["Parameters"] = [{"name": k, "value": str(v)} for k, v in parameters.items()]
    stmt_id = client.execute_statement(**kwargs)["Id"]
    deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000 - DEADLINE_MARGIN
    while True:
        status = client.describe_statement(Id=stmt_id)
        if status["Status"] == "FINISHED":
            break
        if status["Status"] in ("FAILED", "ABORTED"):
            logger.error("Statement %s %s: %s", stmt_id, status["Status"], status.get("Error"))
            raise QueryError(status.get("Error", "Query failed"))
        if time.monotonic() > deadline:
            client.cancel_statement(Id=stmt_id)
            raise QueryError("Query timed out. The data warehouse may be warming up, try again.")
        time.sleep(0.5)  # nosemgrep: arbitrary-sleep, polling Redshift Data API async query

    columns, rows, token = [], [], None
    while True:
        page = client.get_statement_result(Id=stmt_id, **({"NextToken": token} if token else {}))
        columns = columns or [c["name"] for c in page["ColumnMetadata"]]
        rows += [{columns[i]: (None if f.get("isNull") else next(iter(f.values()))) for i, f in enumerate(record)} for record in page["Records"]]
        token = page.get("NextToken")
        if not token or (max_rows is not None and len(rows) > max_rows):
            return columns, rows

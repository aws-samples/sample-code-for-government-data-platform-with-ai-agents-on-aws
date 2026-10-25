"""Runs sql/refresh/ (the rs_* objects) or sql/gold/ (the mv_* area views) against Redshift Serverless; event {"action": "warmup" | "refresh" | "gold"}."""
import json
import logging
import os
import re
import time
from pathlib import Path

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

redshift_data = boto3.client("redshift-data")

WORKGROUP = os.environ["WORKGROUP_NAME"]
DATABASE = os.environ["DATABASE_NAME"]
SECRET_ARN = os.environ["REDSHIFT_SECRET_ARN"]
PLACEHOLDERS = {"gold_database": os.environ["GOLD_DATABASE"], "spectrum_role": os.environ["SPECTRUM_ROLE_ARN"], "region": os.environ["AWS_REGION"]}
SQL_DIR = Path(__file__).parent / "sql"
# The area views join the rs_* objects and are dropped before any of them
MV_VIEWS = ("mv_area_overview", "mv_area_timeseries", "mv_uk_summary")
# Seconds kept back from the Lambda deadline for the cancel and the error report
DEADLINE_MARGIN = 20
LABELS = {"standin": "STAND-IN", "skipped": "SKIPPED", "failed": "FAILED"}

# Redshift quotes the name: relation "x" does not exist. Spectrum reports a gold table missing from the Glue catalog as EntityNotFoundException
MISSING_RELATION = re.compile(r"\b(relation|schema|table)\b.*\bdoes not exist\b", re.IGNORECASE)
MISSING_GOLD = re.compile(MISSING_RELATION.pattern + r"|EntityNotFoundException", re.IGNORECASE)
RS_FROM_GOLD = re.compile(r"CREATE (?:MATERIALIZED VIEW|TABLE) (rs_\w+) AS\s+SELECT\s+(.+?)\s+FROM gold\.\w+", re.DOTALL)
COLUMN = re.compile(r"(\w+)::([A-Z]+(?:\(\d+(?:,\s*\d+)?\))?)|TRY_CAST\(\w+ AS ([A-Z]+(?:\(\d+(?:,\s*\d+)?\))?)\) AS (\w+)", re.IGNORECASE)
CREATES = re.compile(r"CREATE (?:MATERIALIZED VIEW|TABLE) (rs_\w+)")


class Statement:
    def __init__(self, name, sql):
        self.name, self.sql = name, sql


def load_statements(action):
    """The statements of sql/<action>/*.sql in file order. Full-line comments are dropped before splitting on semicolons."""
    statements = []
    for path in sorted((SQL_DIR / action).glob("*.sql")):
        code = "\n".join(line for line in path.read_text().splitlines() if line.strip() and not line.strip().startswith("--"))
        statements += [Statement(f"{action}/{path.stem}", s.strip()) for s in code.split(";") if s.strip()]
    return statements


def render(sql, account_id):
    for key, value in {**PLACEHOLDERS, "account_id": account_id}.items():
        sql = sql.replace(f"{{{key}}}", value)
    return sql


def execute(sql, deadline):
    """Run one statement to completion and return its final describe record. Cancels and raises at the deadline."""
    stmt_id = redshift_data.execute_statement(WorkgroupName=WORKGROUP, Database=DATABASE, SecretArn=SECRET_ARN, Sql=sql)["Id"]
    while True:
        status = redshift_data.describe_statement(Id=stmt_id)
        if status["Status"] in ("FINISHED", "FAILED", "ABORTED"):
            return status
        if time.monotonic() > deadline:
            redshift_data.cancel_statement(Id=stmt_id)
            raise TimeoutError("cancelled, Lambda deadline reached")
        time.sleep(1)  # nosemgrep: arbitrary-sleep, polling Redshift Data API async query


def query_names(sql, deadline):
    """The values of a one-column query."""
    status = execute(sql, deadline)
    if status["Status"] != "FINISHED":
        raise RuntimeError(f"{status.get('Error', status['Status'])} ({sql})")
    if not status.get("ResultRows"):
        return []
    return [next(iter(r[0].values())) for r in redshift_data.get_statement_result(Id=status["Id"])["Records"]]


def drop_statements(deadline):
    """DROPs for every rs_* and mv_* object in public, which also removes tables left by a removed source."""
    # Materialized views are listed in SVV_MV_INFO with a padded CHAR name; pg_tables also shows each view's mv_tbl__* storage table
    mvs = query_names("SELECT TRIM(name) FROM svv_mv_info WHERE schema_name = 'public' AND (name LIKE 'rs\\_%' OR name LIKE 'mv\\_%')", deadline)
    tables = query_names("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE 'rs\\_%' OR tablename LIKE 'mv\\_%') AND tablename NOT LIKE 'mv\\_tbl\\_\\_%'", deadline)
    drops = [Statement(f"drop/{n}", f"DROP MATERIALIZED VIEW IF EXISTS {n} CASCADE") for n in mvs]
    drops += [Statement(f"drop/{n}", f"DROP TABLE IF EXISTS {n} CASCADE") for n in tables]
    logger.info("Dropping %d rs_* and mv_* objects", len(drops))
    return drops


def scoped_statements(statements, tables):
    """The refresh statements for just these rs_* objects: drop the area views, drop and recreate each object, then grant.

    The gold external schema is left alone; the other rs_* objects still read it.
    """
    by_table = {m.group(1): s.name for s in statements if (m := CREATES.search(s.sql))}
    if missing := tables - by_table.keys():
        raise ValueError(f"No refresh SQL for {sorted(missing)}")
    scoped = [Statement(f"drop/{v}", f"DROP MATERIALIZED VIEW IF EXISTS {v} CASCADE") for v in MV_VIEWS]
    for table in sorted(tables):
        scoped += [Statement(f"drop/{table}", f"DROP MATERIALIZED VIEW IF EXISTS {table} CASCADE"), Statement(f"drop/{table}", f"DROP TABLE IF EXISTS {table} CASCADE")]
    files = {by_table[t] for t in tables}
    return scoped + [s for s in statements if s.name in files or s.name.endswith("grant-rs-tables")]


def standin_sql(sql):
    """DDL for an empty table with the columns of an rs_* object built from gold, or None if a column isn't name::TYPE or TRY_CAST(name AS TYPE) AS name."""
    m = RS_FROM_GOLD.fullmatch(sql.strip())
    if not m:
        return None
    columns = []
    for item in re.split(r",\s*\n", m.group(2)):
        c = COLUMN.fullmatch(item.strip())
        if not c:
            return None
        columns.append(f"{c[1]} {c[2]}" if c[1] else f"{c[4]} {c[3]}")
    return f"CREATE TABLE {m.group(1)} ({', '.join(columns)})"


def fresh_deployment(deadline):
    """True before the first refresh has built rs_dim_geography, which every area view joins."""
    return not query_names("SELECT TRIM(name) FROM svv_mv_info WHERE schema_name = 'public' AND name = 'rs_dim_geography'", deadline)


def classify_failure(error, action, fresh, sql):
    """(outcome, stand-in DDL or None) for a FAILED statement: standin, skipped or failed."""
    if action == "refresh" and MISSING_GOLD.search(error):
        # A gold table not built yet gets an empty stand-in, which lets the area views build with nulls for that source
        if standin := standin_sql(sql):
            return "standin", standin
    # Only a fresh deployment may skip an area view whose rs_* object is missing; once refresh has run that is a real failure
    if action == "gold" and fresh and MISSING_RELATION.search(error):
        return "skipped", None
    return "failed", None


def run_statements(statements, action, deadline, account_id):
    """Run every statement, standing in or skipping where allowed, and raise at the end naming the failures."""
    fresh = action == "gold" and fresh_deployment(deadline)
    outcomes, failures = {}, []
    for stmt in statements:
        sql = render(stmt.sql, account_id)
        try:
            status = execute(sql, deadline)
            if status["Status"] == "FINISHED":
                outcomes[stmt.name] = "success"
                continue
            error = status.get("Error", status["Status"])
            outcome, standin = classify_failure(error, action, fresh, sql)
            if standin:
                execute(standin, deadline)
            outcomes[stmt.name] = outcome
            logger.warning("%s %s: %s", LABELS[outcome], stmt.name, error)
            if outcome == "failed":
                failures.append(f"{stmt.name}: {error}")
        except Exception as e:
            outcomes[stmt.name] = "error"
            failures.append(f"{stmt.name}: {e}")
            logger.exception("%s", stmt.name)
    if failures:
        raise RuntimeError(f"{len(failures)} of {len(statements)} SQL statements failed: {'; '.join(failures)}")
    return outcomes


def handler(event, context):
    action = event.get("action", "gold")
    deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000 - DEADLINE_MARGIN
    if action == "warmup":
        status = execute("SELECT 1", deadline)
        logger.info("Warmup: %s", status["Status"])
        return {"warmup": status["Status"]}
    if action not in ("refresh", "gold"):
        raise ValueError(f"Unknown action {action!r}, expected warmup, refresh or gold")

    statements = load_statements(action)
    if action == "refresh":
        if event.get("tables"):
            statements = scoped_statements(statements, set(event["tables"]))
        else:
            statements = drop_statements(deadline) + statements
    account_id = context.invoked_function_arn.split(":")[4]
    outcomes = run_statements(statements, action, deadline, account_id)
    summary = {o: sorted(n for n, v in outcomes.items() if v == o) for o in ("standin", "skipped")}
    logger.info(json.dumps({"message": "Redshift setup done", "action": action, "statements": len(statements), **summary}))
    return {"action": action, "statements": len(statements), **summary}

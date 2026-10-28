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
# The Data API runs at most this many statements in one batch_execute_statement transaction
BATCH_LIMIT = 40
# A refresh builds each rs_* object under this suffix and renames it into place
NEW_SUFFIX = "__new"
LABELS = {"standin": "STAND-IN", "skipped": "SKIPPED", "failed": "FAILED"}

# Redshift quotes the name: relation "x" does not exist. Spectrum reports a gold table missing from the Glue catalog as EntityNotFoundException
MISSING_RELATION = re.compile(r"\b(relation|schema|table)\b.*\bdoes not exist\b", re.IGNORECASE)
MISSING_GOLD = re.compile(MISSING_RELATION.pattern + r"|EntityNotFoundException", re.IGNORECASE)
RS_FROM_GOLD = re.compile(r"CREATE (?:MATERIALIZED VIEW|TABLE) (rs_\w+) AS\s+SELECT\s+(.+?)\s+FROM gold\.(\w+)", re.DOTALL)
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


def _wait(stmt_id, deadline):
    """Poll a Data API statement to its final describe record. Cancels and raises at the deadline."""
    while True:
        status = redshift_data.describe_statement(Id=stmt_id)
        if status["Status"] in ("FINISHED", "FAILED", "ABORTED"):
            return status
        if time.monotonic() > deadline:
            redshift_data.cancel_statement(Id=stmt_id)
            raise TimeoutError("cancelled, Lambda deadline reached")
        time.sleep(1)  # nosemgrep: arbitrary-sleep, polling Redshift Data API async query


def execute(sql, deadline):
    """Run one statement to completion and return its final describe record."""
    stmt_id = redshift_data.execute_statement(WorkgroupName=WORKGROUP, Database=DATABASE, SecretArn=SECRET_ARN, Sql=sql)["Id"]
    return _wait(stmt_id, deadline)


def execute_batch(sqls, deadline):
    """Run the statements as one transaction, so a failure rolls every one of them back. Returns the final describe record."""
    if len(sqls) > BATCH_LIMIT:
        raise ValueError(f"{len(sqls)} statements in one batch, the Data API limit is {BATCH_LIMIT}")
    stmt_id = redshift_data.batch_execute_statement(WorkgroupName=WORKGROUP, Database=DATABASE, SecretArn=SECRET_ARN, Sqls=sqls)["Id"]
    return _wait(stmt_id, deadline)


def batch_error(status):
    """The error of the sub-statement that failed, or the batch status when none did."""
    for sub in status.get("SubStatements", []):
        if sub.get("Error"):
            return sub["Error"]
    return status.get("Error", status["Status"])


def query_names(sql, deadline):
    """The values of a one-column query."""
    status = execute(sql, deadline)
    if status["Status"] != "FINISHED":
        raise RuntimeError(f"{status.get('Error', status['Status'])} ({sql})")
    if not status.get("ResultRows"):
        return []
    return [next(iter(r[0].values())) for r in redshift_data.get_statement_result(Id=status["Id"])["Records"]]


def like(prefix, suffix=""):
    """A LIKE pattern for prefix%suffix with the underscores escaped."""
    return prefix.replace("_", "\\_") + "%" + suffix.replace("_", "\\_")


def public_objects(pattern, deadline):
    """(tables, materialized views) in public whose names match the LIKE pattern. SVV_MV_INFO pads names; pg_tables also lists each view's mv_tbl__* storage table."""
    tables = set(query_names(f"SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE '{pattern}' AND tablename NOT LIKE 'mv\\_tbl\\_\\_%'", deadline))  # nosec B608
    mvs = set(query_names(f"SELECT TRIM(name) FROM svv_mv_info WHERE schema_name = 'public' AND name LIKE '{pattern}'", deadline))  # nosec B608
    return tables - mvs, mvs


def drop_sql(name, mvs):
    """The DROP for an rs_* object. Deployments before the rs_* objects became tables still hold them as materialized views, which DROP TABLE rejects."""
    kind = "MATERIALIZED VIEW" if name in mvs else "TABLE"
    return f"DROP {kind} IF EXISTS {name} CASCADE"


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


def gold_tables(deadline):
    """Names of the tables Spectrum can see in the gold external schema."""
    return set(query_names("SELECT tablename FROM svv_external_tables WHERE schemaname = 'gold'", deadline))


def prepare_refresh(statements, existing_gold, account_id):
    """(name, sql, is_standin) for each rs_* create, with an empty stand-in for any object whose gold table isn't loaded yet."""
    out = []
    for stmt in statements:
        sql = render(stmt.sql, account_id)
        m = RS_FROM_GOLD.fullmatch(sql.strip())
        if m is None:
            continue
        if m.group(3) in existing_gold:
            out.append((m.group(1), sql, False))
            continue
        standin = standin_sql(sql)
        if standin is None:
            raise RuntimeError(f"{stmt.name}: gold table {m.group(3)} is missing and no stand-in can be built from its columns")
        out.append((m.group(1), standin, True))
    return out


def as_new(sql):
    """The create statement with NEW_SUFFIX appended to the object name."""
    return CREATES.sub(lambda m: m.group(0) + NEW_SUFFIX, sql, count=1)


def refresh(tables, deadline, account_id):
    """Rebuild the rs_* objects in tables (all of them when empty) without a gap: build under __new names, then swap each in one transaction.

    A failed build leaves every existing object untouched. A failed swap leaves the old object in place and the __new one for the next run to drop.
    """
    statements = load_statements("refresh")
    schema = [s for s in statements if s.name.endswith("external-schema-gold")]
    grants = [render(s.sql, account_id) for s in statements if s.name.endswith("grant-rs-tables")]
    creates = prepare_refresh(statements, gold_tables(deadline), account_id)
    if tables:
        creates = [c for c in creates if c[0] in tables]
        if missing := set(tables) - {c[0] for c in creates}:
            raise ValueError(f"No refresh SQL for {sorted(missing)}")

    # 1. Leftovers from a failed swap go first
    new_tables, new_mvs = public_objects(like("rs_", NEW_SUFFIX), deadline)
    for name in sorted(new_tables | new_mvs):
        execute(drop_sql(name, new_mvs), deadline)

    # 2. Full refresh only: recreate the external schema in case the Glue database it points at changed
    if not tables:
        for s in schema:
            execute(render(s.sql, account_id), deadline)

    # 3. Build every new object in one transaction; nothing in public changes if this fails
    status = execute_batch([as_new(sql) for _, sql, _ in creates], deadline)
    if status["Status"] != "FINISHED":
        raise RuntimeError(f"Build failed, previous objects untouched: {batch_error(status)}")

    # 4. Drop the area views, swap each object in its own transaction, regrant
    rs_tables, rs_mvs = public_objects(like("rs_"), deadline)
    for v in MV_VIEWS:
        execute(f"DROP MATERIALIZED VIEW IF EXISTS {v} CASCADE", deadline)
    failures = []
    for name, _, _ in creates:
        status = execute_batch([drop_sql(name, rs_mvs), f"ALTER TABLE {name}{NEW_SUFFIX} RENAME TO {name}"], deadline)
        if status["Status"] != "FINISHED":
            failures.append(f"swap/{name}: {batch_error(status)}")
    # 5. Full refresh only: objects left by a removed source
    if not tables:
        built = {name for name, _, _ in creates}
        for name in sorted((rs_tables | rs_mvs) - built):
            if not name.endswith(NEW_SUFFIX):
                execute(drop_sql(name, rs_mvs), deadline)
    for g in grants:
        execute(g, deadline)
    if failures:
        raise RuntimeError(f"{len(failures)} of {len(creates)} swaps failed: {'; '.join(failures)}")
    standin = sorted(name for name, _, is_standin in creates if is_standin)
    for name in standin:
        logger.warning("%s %s: gold table not loaded yet, empty table built", LABELS["standin"], name)
    return {"statements": len(creates), "standin": standin, "skipped": []}


def fresh_deployment(deadline):
    """True before the first refresh has built rs_dim_geography, which every area view joins."""
    tables, mvs = public_objects(like("rs_dim_geography"), deadline)
    return not (tables | mvs)


def classify_failure(error, fresh):
    """The outcome for a FAILED gold statement: skipped or failed."""
    # Only a fresh deployment may skip an area view whose rs_* object is missing; once refresh has run that is a real failure
    if fresh and MISSING_RELATION.search(error):
        return "skipped"
    return "failed"


def run_statements(statements, deadline, account_id):
    """Run every gold statement, skipping where allowed, and raise at the end naming the failures."""
    fresh = fresh_deployment(deadline)
    outcomes, failures = {}, []
    for stmt in statements:
        sql = render(stmt.sql, account_id)
        try:
            status = execute(sql, deadline)
            if status["Status"] == "FINISHED":
                outcomes[stmt.name] = "success"
                continue
            error = status.get("Error", status["Status"])
            outcome = classify_failure(error, fresh)
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
    return {"statements": len(statements), "standin": [], "skipped": sorted(n for n, v in outcomes.items() if v == "skipped")}


def handler(event, context):
    action = event.get("action", "gold")
    deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000 - DEADLINE_MARGIN
    if action == "warmup":
        status = execute("SELECT 1", deadline)
        logger.info("Warmup: %s", status["Status"])
        return {"warmup": status["Status"]}
    if action not in ("refresh", "gold"):
        raise ValueError(f"Unknown action {action!r}, expected warmup, refresh or gold")

    account_id = context.invoked_function_arn.split(":")[4]
    if action == "refresh":
        summary = refresh(set(event.get("tables") or []), deadline, account_id)
    else:
        summary = run_statements(load_statements("gold"), deadline, account_id)
    logger.info(json.dumps({"message": "Redshift setup done", "action": action, **summary}))
    return {"action": action, **summary}

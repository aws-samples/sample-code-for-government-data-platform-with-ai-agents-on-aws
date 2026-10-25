"""Lists the bronze-to-silver jobs to run and the gold and rs_* tables to rebuild: everything when full, otherwise the sources with bronze newer than silver."""
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
s3tables = boto3.client("s3tables")
glue = boto3.client("glue")
dynamodb = boto3.resource("dynamodb")

REGISTRY_TABLE = os.environ["REGISTRY_TABLE"]
DATALAKE_BUCKET = os.environ["DATALAKE_BUCKET"]
SILVER_TABLE_BUCKET_ARN = os.environ["SILVER_TABLE_BUCKET_ARN"]
GLUE_JOB_PREFIX = os.environ["GLUE_JOB_PREFIX"]
# The gold job rebuilds the dimensions on every run, scoped or not
DIMS = ("dim_geography", "dim_time", "dim_region_mapping")
# A fresh deployment, a source with no registry item yet and an input of {"full": true} rebuild everything
FULL = {"full": True, "gold_tables": "all", "rs_tables": []}


def silver_has_tables():
    for page in s3tables.get_paginator("list_namespaces").paginate(tableBucketARN=SILVER_TABLE_BUCKET_ARN):
        for ns in page.get("namespaces", []):
            if s3tables.list_tables(tableBucketARN=SILVER_TABLE_BUCKET_ARN, namespace=ns["namespace"][0], maxTables=1).get("tables"):
                return True
    return False


def bronze_jobs():
    """Every bronze-to-silver Glue job in the account, as first-run job items."""
    names = [n for page in glue.get_paginator("list_jobs").paginate() for n in page.get("JobNames", []) if n.startswith(GLUE_JOB_PREFIX)]
    return [{"source_id": n[len(GLUE_JOB_PREFIX):], "glue_job_name": n, "first_run": True, "bronze_latest": None} for n in names]


def registry_sources():
    items, kwargs = [], {"FilterExpression": "attribute_exists(bronze_s3_prefix) AND attribute_exists(glue_job_name)"}
    while True:
        resp = dynamodb.Table(REGISTRY_TABLE).scan(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def latest_modified(prefix):
    """The newest LastModified under the prefix, or None when it holds no objects."""
    stamps = [o["LastModified"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=DATALAKE_BUCKET, Prefix=prefix) for o in page.get("Contents", [])]
    return max(stamps, default=None)


def scope(changed):
    """The gold tables (comma-separated, for --TABLES) and rs_* objects of the changed sources, plus the dimensions."""
    names = set(DIMS) | {t for s in changed for t in s.get("gold_tables", [])}
    gold = sorted(n for n in names if not n.startswith("rs_"))
    rs = sorted({f"rs_{d}" for d in DIMS} | {n for n in names if n.startswith("rs_")})
    return {"full": False, "gold_tables": ",".join(gold), "rs_tables": rs}


def handler(event, context):
    if not silver_has_tables():
        jobs = bronze_jobs()
        logger.info("Fresh deployment, queuing all %d bronze-to-silver jobs", len(jobs))
        return {"jobs": jobs, "scope": FULL}

    sources = registry_sources()
    registered = {s["glue_job_name"] for s in sources}
    # A job with no registry item is a newly added source; the gold job writes the item after its first build
    jobs = [j for j in bronze_jobs() if j["glue_job_name"] not in registered]
    for j in jobs:
        logger.info("%s: no registry item yet, queuing as a new source", j["source_id"])

    changed = []
    for source in sources:
        bronze_latest = latest_modified(source["bronze_s3_prefix"])
        if bronze_latest is None:
            logger.info("%s: no bronze data at %s, skipping", source["source_id"], source["bronze_s3_prefix"])
            continue
        silver_last = source.get("silver_last_processed")
        if silver_last and bronze_latest <= datetime.fromisoformat(silver_last).replace(tzinfo=timezone.utc):
            logger.info("%s: up to date, skipping", source["source_id"])
            continue
        logger.info("%s: bronze %s newer than silver %s, queuing", source["source_id"], bronze_latest.isoformat(), silver_last)
        # mark-silver-processed stamps this bronze time rather than its own run time, which keeps a file landing mid-run for the next run
        jobs.append({"source_id": source["source_id"], "glue_job_name": source["glue_job_name"], "first_run": False, "bronze_latest": bronze_latest.isoformat()})
        changed.append(source)

    new_source = len(jobs) > len(changed)
    full = bool(event.get("full")) or new_source
    result = FULL if full else scope(changed)
    logger.info("Jobs to run: %s, full: %s%s", [j["source_id"] for j in jobs], full, "" if full else f", tables: {result['gold_tables']}")
    return {"jobs": jobs, "scope": result}

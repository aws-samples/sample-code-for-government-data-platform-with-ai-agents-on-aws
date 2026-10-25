"""Silver to gold: the dimensions and every fact table in gold_tables, then the registry. --TABLES, a comma-separated list, builds only those, and `all` builds every table; the job fails at the end if any table failed."""
import json
import logging
import sys

from awsglue.utils import getResolvedOptions
from glue_common import configure_catalog, start_job
from gold_build import Gold
from gold_tables import TABLES

logger = logging.getLogger()
logger.setLevel("INFO")

args, spark, job = start_job((
    "DATALAKE_BUCKET", "SILVER_DATABASE", "GOLD_DATABASE", "REGISTRY_TABLE", "S3_TABLE_BUCKET_NAME", "S3_TABLE_BUCKET_NAME_SILVER", "INGEST_SCHEDULES"))
configure_catalog(spark, "glue_catalog", args["S3_TABLE_BUCKET_NAME_SILVER"])
configure_catalog(spark, "gold_catalog", args["S3_TABLE_BUCKET_NAME"])
# getResolvedOptions raises on a missing optional argument; --TABLES is read only when passed
selected = set(getResolvedOptions(sys.argv, ["TABLES"])["TABLES"].split(",")) if "--TABLES" in sys.argv else None
if selected == {"all"}:
    selected = None

gold = Gold(spark, args["SILVER_DATABASE"], args["GOLD_DATABASE"], args["DATALAKE_BUCKET"], args["REGISTRY_TABLE"],
            ingest_schedules=json.loads(args["INGEST_SCHEDULES"]))

for spec in TABLES:
    if selected is not None and spec["gold_table"] not in selected and not spec["gold_table"].startswith("dim_"):
        continue
    status = gold.build(spec)
    if spec.get("required") and status != "success":
        raise RuntimeError(f"{spec['gold_table']} failed, aborting: {json.dumps(gold.results[spec['gold_table']])}")
    if status == "success":
        gold.upsert_registry(spec)

results = gold.results
by_status = {s: [k for k, v in results.items() if v["status"] == s] for s in ("success", "skipped", "failed")}
logger.info(json.dumps({"summary": "Gold layer complete", **by_status, "total": len(results)}))

job.commit()

# The tables that built are already committed; failing here makes the Step Function report the run as failed
if by_status["failed"]:
    raise RuntimeError(f"{len(by_status['failed'])} gold table(s) failed: "
                       + json.dumps({k: results[k]["error"][:500] for k in by_status["failed"]}))

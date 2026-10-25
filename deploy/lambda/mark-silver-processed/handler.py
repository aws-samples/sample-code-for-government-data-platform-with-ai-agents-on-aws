"""Stamps silver_last_processed in the data source registry with the bronze time a job was queued for, after its bronze-to-silver Glue job succeeds."""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
REGISTRY_TABLE = os.environ["REGISTRY_TABLE"]


def handler(event, context):
    source_id = event["source_id"]
    # A first-run job is keyed on the Glue job suffix, not the registry source_id; the gold job writes its registry item
    if event.get("first_run"):
        logger.info("%s: first run, the gold job stamps the registry", source_id)
        return {"source_id": source_id, "silver_last_processed": None}

    # The bronze time the job was queued for, not now: a file landing while the job ran stays newer and is picked up next run
    bronze_latest = event["bronze_latest"]
    dynamodb.Table(REGISTRY_TABLE).update_item(
        Key={"source_id": source_id},
        UpdateExpression="SET silver_last_processed = :ts",
        ExpressionAttributeValues={":ts": bronze_latest},
    )
    logger.info("%s: silver_last_processed = %s", source_id, bronze_latest)
    return {"source_id": source_id, "silver_last_processed": bronze_latest}

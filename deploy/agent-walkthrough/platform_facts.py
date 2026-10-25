"""Reads the deployment facts Terraform wrote to S3 and the data source registry for the walkthrough agent."""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, List

import boto3
from strands import tool

logger = logging.getLogger(__name__)

_REGION = os.environ["AWS_DEFAULT_REGION"]
_BUCKET = os.environ.get("PLATFORM_FACTS_BUCKET", "")
_KEY = os.environ.get("PLATFORM_FACTS_KEY", "")
_REGISTRY = os.environ.get("DATA_SOURCE_REGISTRY_TABLE", "")

_REGISTRY_FIELDS = ("source_id", "name", "api_url", "min_year", "max_year", "row_count", "gold_tables", "update_frequency", "ingest_schedule")

_deployment_cache: Dict[str, Any] | None = None


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (set, list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def load_deployment(s3_client=None) -> Dict[str, Any]:
    """Return the Terraform-written facts, cached for the life of the runtime.

    Cache-busting is handled by Terraform: PLATFORM_FACTS_HASH in the runtime
    env rolls on any facts change, which produces a new runtime version and
    starts a fresh container. Do not remove the hash env var in Terraform.
    """
    global _deployment_cache
    if _deployment_cache is not None:
        return _deployment_cache
    if not (_BUCKET and _KEY):
        return {"unavailable": "PLATFORM_FACTS_BUCKET and PLATFORM_FACTS_KEY are not set"}
    client = s3_client or boto3.client("s3", region_name=_REGION)
    body = client.get_object(Bucket=_BUCKET, Key=_KEY)["Body"].read()
    _deployment_cache = json.loads(body)
    return _deployment_cache


def load_sources(table=None) -> List[Dict[str, Any]]:
    """Return what the registry says is loaded, one entry per source."""
    if table is None:
        if not _REGISTRY:
            return []
        table = boto3.resource("dynamodb", region_name=_REGION).Table(_REGISTRY)
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    sources = [
        {k: _plain(item[k]) for k in _REGISTRY_FIELDS if k in item}
        for item in items
    ]
    return sorted(sources, key=lambda s: s.get("source_id", ""))


def platform_facts(s3_client=None, registry_table=None) -> Dict[str, Any]:
    """Combine the deployment facts with the live registry."""
    facts: Dict[str, Any] = {}
    try:
        facts["deployment"] = load_deployment(s3_client)
    except Exception as exc:  # boto errors and bad JSON both leave the answer partial
        logger.warning("platform facts object unavailable: %s", exc)
        facts["deployment"] = {"unavailable": str(exc)}
    try:
        facts["data_sources"] = load_sources(registry_table)
    except Exception as exc:
        logger.warning("data source registry unavailable: %s", exc)
        facts["data_sources"] = {"unavailable": str(exc)}
    return facts


@tool
def get_platform_facts() -> str:
    """Return the facts about THIS deployment of the platform.

    Includes the AWS services and resource names Terraform deployed for each
    layer (ingestion, transformation, serving, agents, web), the models in
    use, what is deliberately not included, and the data sources currently
    loaded with their years and row counts. Use it before describing how the
    platform was built or what data it holds. If a fact is not in the result,
    say it is not recorded rather than guessing.
    """
    return json.dumps(platform_facts(), default=str)

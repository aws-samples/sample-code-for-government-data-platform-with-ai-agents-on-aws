"""Resolves the requested source keys, or "all", to {"tasks": [{"name", "type", "arn"}]} for the ingest Step Function to fan out."""
import json
import os

# Set by Terraform from local.ingest_sources: key to [type, Lambda name or state machine ARN]
SOURCES = {key: {"type": t, "arn": target} for key, (t, target) in json.loads(os.environ["SOURCES_JSON"]).items()}


def handler(event, context):
    requested = event.get("sources", ["all"])

    if "all" in requested:
        requested = list(SOURCES)

    unknown = sorted(set(requested) - set(SOURCES))
    if unknown:
        raise ValueError(f"Unknown sources {unknown}, expected any of {sorted(SOURCES)}")

    return {"tasks": [{"name": name, **SOURCES[name]} for name in dict.fromkeys(requested)]}

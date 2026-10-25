"""AgentCore Gateway tool list_datasets: every source in the data source registry, with the attribution it is owed."""
import logging

import registry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FIELDS = ("source_id", "department", "name", "api_url", "min_year", "max_year", "update_frequency", "gold_tables", "row_count")


def handler(event, context):
    try:
        items = registry.items()
    except Exception:
        logger.exception("list_datasets failed")
        return {"error": "The data source registry could not be read, try again."}

    datasets = sorted(({**{f: item.get(f) for f in FIELDS}, "attribution": registry.statements([item])} for item in items),
                      key=lambda d: d["name"] or "")
    return {"datasets": datasets, "count": len(datasets), "attribution": registry.statements(items)}

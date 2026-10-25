"""Lists the years of Land Registry price paid data not yet in bronze, for the Step Function to fan out one download per year."""
import json
import logging
import os
from datetime import UTC, datetime

import bronze

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

START_YEAR = 1995


def handler(event, context):
    """Every year from 1995 minus those already in bronze; the current year is always included as it updates monthly."""
    current_year = datetime.now(UTC).year
    force = event.get("force", False)
    years = [y for y in range(START_YEAR, current_year + 1)
             if force or y == current_year or not bronze.exists(f"bronze/land-registry/price-paid/year={y}/pp-{y}.csv")]
    logger.info(json.dumps({"message": "Years to download", "total": len(years), "years": years}))
    return {"tasks": [{"years": [y]} for y in years]}

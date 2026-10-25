"""Jobs density: total jobs and jobs per resident by local authority and year (NOMIS NM_57_1)."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_57_1"
S3_KEY = "bronze/nomis/jobs-density/jobs-density-by-la.csv"
# item=1 total jobs, item=3 jobs density
QUERY = f"geography={nomis.TYPE424}&date=latestMINUS30-latest&item=1,3&measures=20100&select=date_name,geography_name,geography_code,item_name,obs_value"


def handler(event, context):
    rows, size = nomis.fetch_to_s3(DATASET, QUERY, S3_KEY)
    return bronze.report("jobs-density", S3_KEY, rows=rows, bytes=size)

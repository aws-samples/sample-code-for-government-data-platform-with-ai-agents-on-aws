"""UK Business Counts: enterprises by local authority and year (NOMIS NM_142_1)."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_142_1"
S3_KEY = "bronze/nomis/business-counts/business-counts-by-la.csv"
# industry=37748736 all industries, employment_sizeband=0 and legal_status=0 all
QUERY = f"geography={nomis.TYPE424}&date=latestMINUS20-latest&industry=37748736&employment_sizeband=0&legal_status=0&measures=20100&select=date_name,geography_name,geography_code,obs_value"


def handler(event, context):
    rows, size = nomis.fetch_to_s3(DATASET, QUERY, S3_KEY)
    return bronze.report("business-counts", S3_KEY, rows=rows, bytes=size)

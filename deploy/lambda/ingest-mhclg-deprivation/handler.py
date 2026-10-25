"""Downloads file 7 of the English Indices of Deprivation 2025 (ranks, scores, deciles, population denominators) to bronze."""
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CSV_URL = "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
S3_KEY = "bronze/mhclg/deprivation/imd2025-file7.csv"


def handler(event, context):
    size = bronze.put(S3_KEY, fetch.get(CSV_URL, timeout=120))
    return bronze.report("imd2025", S3_KEY, bytes=size)

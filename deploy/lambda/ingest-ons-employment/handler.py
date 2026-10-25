"""ONS Annual Population Survey employment, unemployment and inactivity rates by local authority (NOMIS NM_17_5)."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_17_5"
S3_KEY = "bronze/nomis/employment/aps-employment-by-la.csv"
# 53 variables covering rates, work patterns, hours, qualifications, sectors and occupations
VARIABLES = (
    "18,27,36,45,54,63,84,93,102,111,1487"
    ",197,723,733,202,728,738"
    ",434,435,436,437"
    ",290,720,721,722,299,317,344"
    ",1463,1464,1465,1466,1467,1468"
    ",1329,1330,1331,1332,1333,1334,1335,1336,1337,1338"
    ",1815,1816,1817,1818,1819,1820,1821,1822,1823"
)
QUERY = f"geography={nomis.TYPE424}&date=latestMINUS99-latest&variable={VARIABLES}&measures=20599&select=date_name,geography_name,geography_code,variable_name,measures_name,obs_value"


def handler(event, context):
    rows, size = nomis.fetch_to_s3(DATASET, QUERY, S3_KEY)
    return bronze.report("ons-employment", S3_KEY, rows=rows, bytes=size)

"""DWP Universal Credit: people on UC by local authority and month, from Stat-Xplore."""
import csv
import io
import logging
import os

import bronze
import statxplore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATABASE = "str:database:UC_Monthly"
MEASURE = "str:count:UC_Monthly:V_F_UC_CASELOAD_FULL"
GEO_FIELD = "str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE"
DATE_FIELD = "str:field:UC_Monthly:F_UC_DATE:DATE_NAME"
LA_VALUESET = "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LA_TO_REGION"
S3_KEY = "bronze/dwp/universal-credit/uc-by-local-authority.csv"


def handler(event, context):
    key = statxplore.api_key()
    result = statxplore.table(key, DATABASE, MEASURE, GEO_FIELD, statxplore.value_ids(key, LA_VALUESET), DATE_FIELD)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["geography_code", "la_name", "date_name", "claimant_count"])
    rows = 0
    for code, name, date_label, _, count in statxplore.rows(result):
        writer.writerow([code, name, date_label, count])
        rows += 1

    size = bronze.put(S3_KEY, out.getvalue().encode())
    return bronze.report("universal-credit", S3_KEY, rows=rows, bytes=size)

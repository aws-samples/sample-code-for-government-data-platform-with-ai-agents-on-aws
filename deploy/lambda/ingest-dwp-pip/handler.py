"""DWP Personal Independence Payment: cases with entitlement by local authority and month, from Stat-Xplore."""
import csv
import io
import json
import logging
import os

import bronze
import statxplore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATABASE = "str:database:PIP_Monthly_new"
MEASURE = "str:count:PIP_Monthly_new:V_F_PIP_MONTHLY"
GEO_FIELD = "str:field:PIP_Monthly_new:V_F_PIP_MONTHLY:WARD_CODE"
DATE_FIELD = "str:field:PIP_Monthly_new:F_PIP_DATE:DATE2"
LA_VALUESET = "str:valueset:PIP_Monthly_new:V_F_PIP_MONTHLY:WARD_CODE:V_C_MASTERGEOG21_LA_TO_REGION"
DATE_VALUESET = "str:valueset:PIP_Monthly_new:F_PIP_DATE:DATE2:C_PIP_DATE"
# An all-month query 504s; 12 months a request takes about 17 s
DATE_CHUNK = 12
S3_KEY = "bronze/dwp/pip/pip-by-local-authority.csv"


def handler(event, context):
    key = statxplore.api_key()
    la_ids = statxplore.value_ids(key, LA_VALUESET)
    date_ids = statxplore.value_ids(key, DATE_VALUESET)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["geography_code", "la_name", "date_name", "caseload_count"])
    rows = 0
    for start in range(0, len(date_ids), DATE_CHUNK):
        chunk = date_ids[start:start + DATE_CHUNK]
        logger.info(json.dumps({"message": "Querying PIP date chunk", "chunk": start // DATE_CHUNK + 1, "months": len(chunk)}))
        # The date labels are "Jan-19"; the URI suffix is the sortable yyyymm
        for code, name, _, date_yyyymm, count in statxplore.rows(statxplore.table(key, DATABASE, MEASURE, GEO_FIELD, la_ids, DATE_FIELD, chunk)):
            writer.writerow([code, name, date_yyyymm, count])
            rows += 1

    size = bronze.put(S3_KEY, out.getvalue().encode())
    return bronze.report("pip", S3_KEY, rows=rows, bytes=size)

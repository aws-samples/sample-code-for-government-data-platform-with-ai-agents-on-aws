"""DWP Children in Low Income Families: children under 16 by local authority and year, three measures, from Stat-Xplore."""
import csv
import io
import json
import logging
import os

import bronze
import statxplore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# One Stat-Xplore database per measure
MEASURES = {
    "relative_bhc": ("CILIF_REL", "V_F_CILIF_REL", "F_CILIF_DATE"),
    "absolute_bhc": ("CILIF_ABS", "V_F_CILIF_ABS", "F_CILIF_DATE"),
    "relative_ahc": ("CILIF_AHC", "V_F_CILIF_AHC", "F_CILIF_DATE_AHC"),
}
S3_KEY = "bronze/dwp/cilif/children-low-income-by-local-authority.csv"


def _query(key, db, fact, date_table):
    geo_field = f"str:field:{db}:{fact}:WARD_CODE"
    la_ids = statxplore.value_ids(key, f"str:valueset:{db}:{fact}:WARD_CODE:V_C_MASTERGEOG21_LA_TO_REGION_NI")
    return statxplore.table(key, f"str:database:{db}", f"str:count:{db}:{fact}", geo_field, la_ids, f"str:field:{db}:{date_table}:DATE_NAME")


def handler(event, context):
    key = statxplore.api_key()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["geography_code", "la_name", "date_name", "measure", "children_count"])
    rows = 0
    for measure, ids in MEASURES.items():
        measure_rows = 0
        for code, name, date_label, _, count in statxplore.rows(_query(key, *ids)):
            writer.writerow([code, name, date_label, measure, count])
            measure_rows += 1
        logger.info(json.dumps({"message": "CiLIF measure fetched", "measure": measure, "rows": measure_rows}))
        rows += measure_rows

    size = bronze.put(S3_KEY, out.getvalue().encode())
    return bronze.report("cilif", S3_KEY, rows=rows, bytes=size)

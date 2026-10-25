"""ONS live births (NOMIS NM_205_1) and deaths (NM_161_1) by local authority and year."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

PREFIX = "bronze/ons/births-deaths/"
SELECT = "select=date_name,geography_name,geography_code,obs_value"
# age_of_mother=0 all ages; gender=0, cause_of_death=0, age=0 all, measure=1 count
QUERIES = {
    "births": ("NM_205_1", f"geography={nomis.TYPE424}&date=latestMINUS20-latest&age_of_mother=0&measures=20100&{SELECT}"),
    "deaths": ("NM_161_1", f"geography={nomis.TYPE424}&date=latestMINUS20-latest&gender=0&cause_of_death=0&age=0&measure=1&measures=20100&{SELECT}"),
}


def handler(event, context):
    files = {}
    for name, (dataset, query) in QUERIES.items():
        key = f"{PREFIX}{name}-by-la.csv"
        rows, size = nomis.fetch_to_s3(dataset, query, key)
        files[name] = {"s3_key": key, "rows": rows, "bytes": size}
    return bronze.report("births-deaths", files=files, rows=sum(f["rows"] for f in files.values()))

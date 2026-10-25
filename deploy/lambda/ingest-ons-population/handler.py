"""Downloads ONS mid-year population estimates by single year of age and sex (NOMIS NM_2002_1) to bronze."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_2002_1"
S3_KEY = "bronze/ons/population/population-by-la.csv"
# TYPE462 metropolitan counties, TYPE480 regions, TYPE499 countries
AREA_TYPES = f"{nomis.TYPE424},TYPE462,TYPE480,TYPE499"
# Ages 0 to 89 (codes 101-190), 90+ (191) and all ages (200), for all people, males and females
DIMENSIONS = "date=2001-latest&gender=0,1,2&c_age=101...191,200&measures=20100&select=date_name,geography_code,geography_name,gender,c_age,obs_value"


def _county_codes():
    """The current shire county codes (E10), which NOMIS only lists alongside unitaries in TYPE423."""
    lines = nomis.get_page(nomis.dataset_url(DATASET), "geography=TYPE423&date=latest&gender=0&c_age=200&measures=20100&select=geography_code")
    return sorted({line.strip(b'"').decode() for line in lines[1:] if line.startswith(b'"E10')})


def handler(event, context):
    counties = _county_codes()
    if not counties:
        raise RuntimeError("NOMIS TYPE423 returned no shire county codes")
    rows, size = nomis.fetch_to_s3(DATASET, f"geography={AREA_TYPES},{','.join(counties)}&{DIMENSIONS}", S3_KEY)
    return bronze.report("ons-population", S3_KEY, rows=rows, bytes=size, counties=len(counties))

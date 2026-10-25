"""Downloads the headline Annual Population Survey variables by local authority (NOMIS NM_17_5) to bronze."""
import logging
import os

import bronze
import nomis

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DATASET = "NM_17_5"
S3_KEY = "bronze/nomis/aps/annual-population-survey.csv"
# 43 headline variables covering economic activity, employment, qualifications and industry
VARIABLES = ",".join([
    # Economic activity (headline + gender)
    "18",   # Economic activity rate - aged 16-64
    "27",   # Economic activity rate males - aged 16-64
    "28",   # Economic activity rate females - aged 16-64
    # Employment (headline + gender + age)
    "45",   # Employment rate - aged 16-64
    "53",   # Employment rate males - aged 16-64
    "54",   # Employment rate females - aged 16-64
    "46",   # Employment rate - aged 16-19
    "47",   # Employment rate - aged 20-24
    "50",   # Employment rate - aged 50+
    # Unemployment (headline + gender + age)
    "84",   # Unemployment rate - aged 16-64
    "92",   # Unemployment rate males - aged 16-64
    "93",   # Unemployment rate females - aged 16-64
    "85",   # Unemployment rate - aged 16-19
    "86",   # Unemployment rate - aged 20-24
    "89",   # Unemployment rate - aged 50+
    # Economic inactivity (headline + gender)
    "111",  # % economically inactive - aged 16-64
    "119",  # % economically inactive males - aged 16-64
    "120",  # % economically inactive females - aged 16-64
    # Working patterns
    "197",  # % working full-time - aged 16-64
    "202",  # % working part-time - aged 16-64
    "72",   # % who are employees - aged 16-64
    "74",   # % who are self-employed - aged 16-64
    # Industry (aged 16-64)
    "228",  # % in manufacturing - aged 16-64
    "229",  # % in construction - aged 16-64
    "231",  # % in transport & comms - aged 16-64
    "232",  # % in banking/finance/insurance - aged 16-64
    "233",  # % in public admin/education/health - aged 16-64
    # Industry (all ages)
    "218",  # % all in manufacturing
    "219",  # % all in construction
    "221",  # % all in transport & comms
    "222",  # % all in banking/finance
    "223",  # % all in public admin/education/health
    # Qualifications (aged 16-64)
    "290",  # % with NVQ4+ - aged 16-64
    "299",  # % with NVQ3 only - aged 16-64
    "317",  # % with NVQ2 only - aged 16-64
    "326",  # % with NVQ1 only - aged 16-64
    "335",  # % with other qualifications - aged 16-64
    "344",  # % with no qualifications - aged 16-64
    # Economically active qualifications (aged 16-64)
    "353",  # % economically active with NVQ4+ - aged 16-64
    "362",  # % economically active with NVQ3 only - aged 16-64
    "380",  # % economically active with NVQ2 only - aged 16-64
    "389",  # % economically active with NVQ1 only - aged 16-64
    "398",  # % economically active with other qualifications - aged 16-64
])
QUERY = f"geography={nomis.TYPE424}&date=latestMINUS83-latest&variable={VARIABLES}&measures=20599&select=date_name,geography_name,geography_code,variable_name,measures_name,obs_value"


def handler(event, context):
    rows, size = nomis.fetch_to_s3(DATASET, QUERY, S3_KEY)
    return bronze.report("nomis-aps", S3_KEY, rows=rows, bytes=size)

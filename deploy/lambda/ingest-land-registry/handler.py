"""Downloads one year of HM Land Registry price paid data per invocation to bronze."""
import logging
import os

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BASE_URL = "https://s3.eu-west-1.amazonaws.com/prod1.publicdata.landregistry.gov.uk"


def handler(event, context):
    """Downloads the years in event["years"]; get-land-registry-years decides which."""
    results = []
    for year in event["years"]:
        key = f"bronze/land-registry/price-paid/year={year}/pp-{year}.csv"
        with fetch.request(f"{BASE_URL}/pp-{year}.csv", timeout=300) as resp:
            size = int(resp.headers.get("Content-Length", 0))
            bronze.s3.upload_fileobj(resp, bronze.BUCKET, key, ExtraArgs={"ContentType": "text/csv"})
        results.append({"year": year, "s3_key": key, "bytes": size})
    return bronze.report("land-registry-price-paid", results=results)

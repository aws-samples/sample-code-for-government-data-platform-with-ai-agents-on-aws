"""NOMIS API (https://www.nomisweb.co.uk/api/v01) CSV queries, paged with recordoffset: NOMIS returns at most 25,000 rows a request and drops the rest silently."""
import json
import logging
import tempfile

import bronze
import fetch

logger = logging.getLogger()

PAGE_ROWS = 25000
# Local authority districts and unitaries as of April 2023, with the back series on those boundaries
TYPE424 = "TYPE424"


def dataset_url(dataset):
    return f"https://www.nomisweb.co.uk/api/v01/dataset/{dataset}.data.csv"


def get_page(base, query, offset=0):
    """The lines of one page of a NOMIS CSV query, header first."""
    return fetch.get(f"{base}?{query}&recordoffset={offset}", timeout=120).splitlines()


def fetch_all(base, query, out):
    """Write every row of a NOMIS query to out as CSV with one header and return the row count."""
    offset, pages = 0, 0
    while True:
        lines = get_page(base, query, offset)
        if not lines:
            # An empty first page would otherwise write a zero-byte file that silver reads as no rows
            if offset == 0:
                raise RuntimeError(f"NOMIS returned nothing for {base}?{query}")
            break
        if offset == 0:
            out.write(lines[0] + b"\n")
        rows = lines[1:]
        out.writelines(row + b"\n" for row in rows)
        offset += len(rows)
        pages += 1
        if pages % 10 == 0:
            logger.info(json.dumps({"message": "Fetching from NOMIS", "pages": pages, "rows_so_far": offset}))
        if len(rows) < PAGE_ROWS:
            break
    return offset


def fetch_to_s3(dataset, query, key):
    """Page a NOMIS query through a temp file into bronze and return (rows, bytes)."""
    with tempfile.TemporaryFile() as out:
        rows = fetch_all(dataset_url(dataset), query, out)
        size = bronze.upload(key, out)
    return rows, size

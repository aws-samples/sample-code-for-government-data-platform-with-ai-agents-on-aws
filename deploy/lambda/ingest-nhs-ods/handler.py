"""Downloads active GP practices, pharmacies and trusts from the NHS ORD API to bronze, one dated snapshot per type."""
import json
import logging
import os
from datetime import UTC, datetime

import bronze
import fetch

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

API = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
PAGE_SIZE = 1000
ORG_TYPES = {"gp-practices": "RO177", "pharmacies": "RO182", "nhs-trusts": "RO197"}


def _organisations(role_id):
    """Every active organisation with the role. Pages with Offset (the API ignores _startIndex and rejects Offset=0), deduped on OrgId."""
    orgs, seen, offset, total = [], set(), 0, None
    while True:
        url = f"{API}?PrimaryRoleId={role_id}&Status=Active&Limit={PAGE_SIZE}" + (f"&Offset={offset}" if offset else "")
        with fetch.request(url, timeout=30, headers={"Accept": "application/json"}) as resp:
            if total is None and resp.headers.get("x-total-count"):
                total = int(resp.headers["x-total-count"])
            batch = json.loads(resp.read()).get("Organisations", [])
        new = [o for o in batch if o.get("OrgId") and o["OrgId"] not in seen]
        seen.update(o["OrgId"] for o in new)
        orgs += new
        logger.info(json.dumps({"message": "Fetched organisations", "role_id": role_id, "offset": offset, "new": len(new), "total_so_far": len(orgs), "total_expected": total}))
        if len(batch) < PAGE_SIZE or not new or (total is not None and len(orgs) >= total):
            return orgs
        offset += PAGE_SIZE


def handler(event, context):
    snapshot_date = datetime.now(UTC).strftime("%Y-%m-%d")
    files = {}
    for org_type, role_id in ORG_TYPES.items():
        orgs = _organisations(role_id)
        key = f"bronze/nhs/ods/{org_type}/snapshot_date={snapshot_date}/organisations.json"
        bronze.put(key, json.dumps(orgs, indent=2).encode(), "application/json")
        files[org_type] = {"s3_key": key, "count": len(orgs)}
    return bronze.report("nhs-ods", files=files)

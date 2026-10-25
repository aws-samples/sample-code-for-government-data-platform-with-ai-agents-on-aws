"""The ONS beta API (https://api.beta.ons.gov.uk/v1): which version of a dataset edition to download."""
import fetch

API_BASE = "https://api.beta.ons.gov.uk/v1"


def editions(dataset):
    """The edition names of a dataset, sorted."""
    return sorted(e["edition"] for e in fetch.get_json(f"{API_BASE}/datasets/{dataset}/editions", timeout=30)["items"])


def latest_version(dataset, edition):
    """(version number, CSV download URL) of the highest-numbered version of an edition."""
    versions = fetch.get_json(f"{API_BASE}/datasets/{dataset}/editions/{edition}/versions", timeout=30)["items"]
    latest = max(versions, key=lambda v: v["version"])
    return latest["version"], latest["downloads"]["csv"]["href"]

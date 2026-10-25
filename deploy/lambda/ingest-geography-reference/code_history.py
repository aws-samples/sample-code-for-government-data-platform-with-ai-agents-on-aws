"""Builds the local authority code history from the latest ONS Code History Database (CHD) release."""
import csv
import io
import re
import tempfile
import zipfile
from datetime import datetime

import fetch

SEARCH_URL = (
    "https://geoportal.statistics.gov.uk/api/search/v1/collections/all/items"
    "?q=%22Code%20History%20Database%22&type=CSV%20Collection&limit=100"
)
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}/data"
TITLE = re.compile(r"^Code History Database \((\w+) (\d{4})\) for the UK")
# Districts, unitaries, metropolitan districts, London boroughs, Welsh principal areas, Scottish councils, NI districts
LA_ENTITIES = {"E06", "E07", "E08", "E09", "W06", "S12", "N09"}
HEADER = ["old_code", "old_name", "current_code", "current_name", "changed_on", "merged"]


def latest_release():
    """Return (item id, release label) of the newest CHD release on the Open Geography Portal."""
    items = fetch.get_json(SEARCH_URL)["features"]
    releases = []
    for item in items:
        m = TITLE.match(item["properties"]["title"])
        if m:
            releases.append((datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y"), item["id"]))
    if not releases:
        raise RuntimeError("No Code History Database release found on the Open Geography Portal")
    released, item_id = max(releases)
    return item_id, released.strftime("%B %Y")


def _rows(zf, name):
    # The CHD CSVs mix encodings; codes are ASCII and Latin-1 reads every byte
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"))


def resolve(history, changes):
    """Resolve every terminated local authority code to its live successor.

    history: {code: (name, is_live)}. changes: [(old_code, new_code, new_name, oper_date)].
    A code split by a boundary transfer keeps the successor with its own name.
    """
    successors = {}
    for old, new, new_name, oper_date in changes:
        successors.setdefault(old, {})[new] = (new_name, oper_date)

    def current(code, seen):
        if history.get(code, ("", False))[1] or code not in successors or code in seen:
            return code
        options = successors[code]
        if len(options) > 1:
            same_name = [c for c, (n, _) in options.items() if n == history.get(code, ("",))[0]]
            if len(same_name) != 1:
                return None
            options = {same_name[0]: options[same_name[0]]}
        return current(next(iter(options)), seen | {code})

    resolved = {}
    for old in successors:
        if history.get(old, ("", True))[1]:
            continue
        new = current(old, frozenset())
        if new and new != old and history.get(new, ("", False))[1]:
            first_change = min(v[1] for v in successors[old].values())
            resolved[old] = (new, first_change)
    # Same name means the area was recoded; a different name means it merged into a new area
    return [
        (old, history.get(old, ("",))[0], new, history[new][0], changed_on, history.get(old, ("",))[0] != history[new][0])
        for old, (new, changed_on) in sorted(resolved.items())
    ]


def build():
    """Download the latest CHD and return (CSV bytes, release label, row count)."""
    item_id, release = latest_release()
    with tempfile.TemporaryFile() as tmp:
        fetch.download(ITEM_URL.format(item_id=item_id), tmp, timeout=300)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as zf:
            history = {}
            for r in _rows(zf, "ChangeHistory.csv"):
                if r["ENTITYCD"] in LA_ENTITIES:
                    name, live = history.get(r["GEOGCD"], (r["GEOGNM"], False))
                    is_live = r["STATUS"] == "live"
                    history[r["GEOGCD"]] = (r["GEOGNM"] if is_live or not live else name, live or is_live)
            changes = [
                (r["GEOGCD_P"], r["GEOGCD"], r["GEOGNM"], datetime.strptime(r["OPER_DATE"][:10], "%d/%m/%Y").date().isoformat())
                for r in _rows(zf, "Changes.csv")
                if r["GEOGCD"][:3] in LA_ENTITIES and r["GEOGCD_P"][:3] in LA_ENTITIES
            ]
    rows = resolve(history, changes)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8"), release, len(rows)

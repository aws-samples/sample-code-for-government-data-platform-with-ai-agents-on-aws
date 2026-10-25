"""Builds a choropleth map config from a SQL query the webapp colours by local authority."""
import json
import re
from strands import tool
from . import run_sql


@tool
def create_choropleth(
    title: str,
    sql: str,
    value_column: str,
    label_format: str = "{value}",
) -> str:
    """Create a choropleth map that colours local authority boundaries by a metric value.

    ONLY use this tool when the user explicitly asks for a "choropleth" map.
    Do NOT use it just because a query involves multiple areas or national data.

    The tool executes the SQL query directly, the data never enters the conversation.

    For local detail (e.g. crime hotspots in one area), use create_map instead.

    Args:
        title: Map title describing what the data shows.
        sql: SQL query that must return geography_code, geography_name, and a numeric column.
        value_column: Name of the numeric column to use for colour scaling.
        label_format: Format string for popup labels. Use {value} as placeholder.
            Defaults to showing the raw value.
    """
    if violation := run_sql.read_only_violation(sql):
        return f"Error: {violation}"
    result = run_sql.execute_and_track(sql)
    if "error" in result:
        return f"Choropleth query failed: {result['error']}"
    if not result["rows"]:
        return "Choropleth query returned no rows."

    choropleth = []
    for row in result["rows"]:
        try:
            val = float(row.get(value_column))
        except (TypeError, ValueError):
            continue
        label = re.sub(r"\{value[^}]*\}", f"{val:,.0f}", label_format)
        choropleth.append({
            "geography_code": row.get("geography_code", ""),
            "name": row.get("geography_name", ""),
            "value": val,
            "label": label,
        })
    return json.dumps({"__map__": True, "config": {"title": title, "choropleth": choropleth}})

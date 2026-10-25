"""Builds a point marker map config the webapp renders with MapLibre."""
import json
from strands import tool


MAX_POINTS = 50


@tool
def create_map(
    title: str,
    points: list[dict],
) -> str:
    """Create a point marker map from geographic data. Returns JSON that the webapp renders as a MapLibre GL map.

    Use for local detail: crime hotspots in one area, school locations, specific places.
    For national/regional comparisons across many areas, use create_choropleth instead.
    Limit to the top 30-50 most significant points. Do not map entire datasets.

    Args:
        title: Map title describing what the data shows.
        points: List of point marker objects. Each must have:
            - name (str): Location name (e.g. "Camden", "Woking")
            - lat (float): Latitude
            - lng (float): Longitude
            - value (float): Metric value for colour coding
            - label (str): Display label (e.g. "£450,000" or "1,234 crimes")
    """
    if len(points) > MAX_POINTS:
        points = sorted(points, key=lambda p: p.get("value") or 0, reverse=True)[:MAX_POINTS]
    config = {"title": title, "points": points}
    return json.dumps({"__map__": True, "config": config})

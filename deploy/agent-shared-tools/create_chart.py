"""Builds a Chart.js config the webapp renders."""
import json
from strands import tool


@tool
def create_chart(
    chart_type: str,
    title: str,
    labels: list[str],
    datasets: list[dict],
) -> str:
    """Create a chart visualisation from query results. Returns JSON that the webapp renders as an interactive chart.

    Use this tool when the user asks for a visualisation, graph, chart, or when data would be
    better understood visually (comparisons, trends, distributions).

    Args:
        chart_type: Type of chart. One of: bar, line, pie, doughnut, scatter, radar.
        title: Chart title describing what the data shows.
        labels: List of labels for the x-axis or categories (e.g. area names, years).
        datasets: List of dataset objects. Each must have:
            - label (str): Dataset name (e.g. "House Prices", "Crime Rate")
            - data (list): Numeric values matching the labels
            Optional:
            - backgroundColor (str or list): Colour(s) for bars/points
            - borderColor (str): Line/border colour
    """
    config = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": datasets,
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": title,
                },
                "legend": {
                    "display": len(datasets) > 1,
                },
            },
        },
    }

    return json.dumps({"__chart__": True, "config": config})

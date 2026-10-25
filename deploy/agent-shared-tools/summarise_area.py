"""Builds a local authority profile with charts from mv_area_overview, mv_area_timeseries and the crime, school and HPI facts."""
import json
from concurrent.futures import ThreadPoolExecutor
from strands import tool
from . import run_sql

OVERVIEW_SQL = "SELECT * FROM mv_area_overview WHERE geography_name ILIKE :area_name ORDER BY geography_name LIMIT 1"
NATIONAL_SQL = """
    SELECT AVG(life_satisfaction) as life_satisfaction,
           AVG(happiness) as happiness,
           AVG(anxiety) as anxiety,
           AVG(CAST(avg_attainment_8 AS FLOAT)) as avg_attainment_8,
           AVG(median_house_price) as median_house_price,
           AVG(avg_imd_score) as avg_imd_score,
           AVG(median_weekly_pay) as median_weekly_pay,
           AVG(jobs_density) as jobs_density,
           AVG(pm25_total) as pm25_total,
           AVG(total_gva) as total_gva,
           AVG(total_jobs) as total_jobs,
           AVG(active_enterprises) as active_enterprises,
           AVG(employment_rate) as employment_rate,
           AVG(unemployment_rate) as unemployment_rate,
           AVG(crime_rate_per_1000) as crime_rate_per_1000,
           AVG(total_service_spend_k) as total_service_spend_k,
           AVG(latest_hb_claimants) as latest_hb_claimants,
           AVG(latest_children_low_income) as latest_children_low_income,
           AVG(latest_pip_claimants) as latest_pip_claimants
    FROM mv_area_overview
    WHERE total_population IS NOT NULL
"""
TIMESERIES_SQL = """
    SELECT calendar_year, total_population, employment_rate, unemployment_rate, total_jobs, active_enterprises
    FROM mv_area_timeseries
    WHERE geography_code = :geography_code
    ORDER BY calendar_year
"""
CRIME_SQL = """
    SELECT street_name, avg_latitude, avg_longitude, SUM(crime_count) as crimes
    FROM rs_fact_crime
    WHERE geography_code = :geography_code
    GROUP BY street_name, avg_latitude, avg_longitude
    ORDER BY crimes DESC
    LIMIT 20
"""
SCHOOLS_SQL = """
    SELECT school_name, attainment8_average
    FROM rs_fact_school_detail
    WHERE geography_code = :geography_code
      AND calendar_year = (SELECT MAX(calendar_year) FROM rs_fact_school_detail)
      AND breakdown_topic = 'Total'
      AND attainment8_average IS NOT NULL
    ORDER BY attainment8_average DESC
    LIMIT 10
"""
HPI_SQL = """
    SELECT calendar_year,
           ROUND(AVG(average_price), 0) as avg_price,
           ROUND(AVG(annual_change_pct), 1) as annual_change_pct
    FROM rs_fact_hpi
    WHERE geography_code = :geography_code
    GROUP BY calendar_year
    ORDER BY calendar_year
"""

# (label, overview column, min, max, lower is better) for the 0-100 radar scale
RADAR_METRICS = [
    ("Life satisfaction", "life_satisfaction", 5, 9, False),
    ("Happiness", "happiness", 5, 9, False),
    ("Low anxiety", "anxiety", 1, 5, True),
    ("School performance", "avg_attainment_8", 20, 70, False),
    ("Earnings", "median_weekly_pay", 300, 800, False),
    ("Low deprivation", "avg_imd_score", 5, 45, True),
    ("Jobs density", "jobs_density", 0.3, 1.5, False),
    ("Clean air", "pm25_total", 4, 12, True),
]
LOWER_IS_BETTER = {"anxiety", "avg_imd_score", "pct_most_deprived", "pm25_total", "pm25_anthropogenic", "unemployment_rate", "crime_rate_per_1000"}
AVERAGE_LABEL = "LA average"

BLUE, GREEN, RED, GREY = "#1d70b8", "#00703c", "#d4351c", "#b1b4b6"


def _rows(sql, parameters=None):
    """Rows of a profile sub-query, or [] when it fails; one missing panel shouldn't lose the profile."""
    result = run_sql.execute_and_track(sql, parameters=parameters, max_rows=None)
    return [] if "error" in result else result["rows"]


def _chart(config):
    return json.dumps({"__chart__": True, "config": config})


def _line(title, labels, series, axes):
    """Two-axis line chart: series is [(label, values, colour, axis id)], axes is {axis id: title}."""
    datasets = [{"label": lab, "data": vals, "borderColor": colour, "fill": False, "yAxisID": axis}
                for lab, vals, colour, axis in series if any(v is not None for v in vals)]
    if not datasets:
        return ""
    scales = {}
    for i, (axis, axis_title) in enumerate(axes.items()):
        scales[axis] = {"position": "left" if i == 0 else "right", "title": {"display": True, "text": axis_title}}
        if i:
            scales[axis]["grid"] = {"drawOnChartArea": False}
    return _chart({"type": "line", "data": {"labels": labels, "datasets": datasets},
                   "options": {"responsive": True, "scales": scales, "plugins": {"title": {"display": True, "text": title}}}})


def _compare(key, area_val, nat_val):
    """similar, above, below, better or worse than the average, or None when either side is missing or not numeric."""
    if area_val is None or nat_val is None:
        return None
    try:
        a, n = float(area_val), float(nat_val)
    except (ValueError, TypeError):
        return None
    if n == 0 or abs(a - n) / abs(n) * 100 < 3:
        return f"similar to {AVERAGE_LABEL} {round(n, 1)}"
    if key in LOWER_IS_BETTER:
        return f"{'better' if a < n else 'worse'} than {AVERAGE_LABEL} {round(n, 1)}"
    return f"{'above' if a > n else 'below'} {AVERAGE_LABEL} {round(n, 1)}"


def _radar(geo_name, area, national):
    labels, area_scores, nat_scores = [], [], []
    for label, key, lo, hi, invert in RADAR_METRICS:
        if area.get(key) is None or national.get(key) is None:
            continue
        scores = [max(0, min(100, (float(v) - lo) / (hi - lo) * 100)) for v in (area[key], national[key])]
        if invert:
            scores = [100 - s for s in scores]
        labels.append(label)
        area_scores.append(round(scores[0], 1))
        nat_scores.append(round(scores[1], 1))
    return _chart({
        "type": "radar",
        "data": {"labels": labels, "datasets": [
            {"label": geo_name, "data": area_scores, "backgroundColor": "rgba(29, 112, 184, 0.2)", "borderColor": BLUE, "pointBackgroundColor": BLUE},
            {"label": AVERAGE_LABEL, "data": nat_scores, "backgroundColor": "rgba(177, 180, 182, 0.2)", "borderColor": GREY, "pointBackgroundColor": GREY},
        ]},
        "options": {"responsive": True, "scales": {"r": {"beginAtZero": True, "max": 100, "ticks": {"display": False}}},
                    "plugins": {"title": {"display": True, "text": f"{geo_name} vs {AVERAGE_LABEL}"}}},
    })


# Key stats shown in the table: (label, overview column, format, period column)
KEY_STATS = [
    ("Population", "total_population", "{:,.0f}", "population_year"),
    ("Median weekly pay", "median_weekly_pay", "£{:,.0f}", "earnings_year"),
    ("Average house price", "median_house_price", "£{:,.0f}", "house_prices_year"),
    ("Employment rate", "employment_rate", "{:.1f}%", "employment_period"),
    ("Unemployment rate", "unemployment_rate", "{:.1f}%", "employment_period"),
    ("Crime rate per 1,000", "crime_rate_per_1000", "{:.1f}", "crime_period"),
    ("Attainment 8", "avg_attainment_8", "{:.1f}", "school_performance_year"),
    ("Deprivation score (IMD)", "avg_imd_score", "{:.1f}", "deprivation_year"),
    ("Life satisfaction (0-10)", "life_satisfaction", "{:.2f}", "wellbeing_year"),
    ("PM2.5 (µg/m³)", "pm25_total", "{:.1f}", "air_quality_year"),
    ("Jobs density", "jobs_density", "{:.2f}", "jobs_density_year"),
]


def _fmt(value, fmt):
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return str(value)


def _pct_change(first, last):
    try:
        a, b = float(first), float(last)
    except (TypeError, ValueError):
        return None
    return None if a == 0 else (b - a) / a * 100


def _trend_sentence(label, rows, col, fmt, unit=""):
    """'<label> was X in <first year> and Y in <last year>, up N%.' from the first and last non-null rows."""
    pts = [(r["calendar_year"], r[col]) for r in rows if r.get(col) is not None]
    if len(pts) < 2:
        return ""
    (y0, v0), (y1, v1) = pts[0], pts[-1]
    change = _pct_change(v0, v1)
    direction = "" if change is None else (f", up {change:.0f}%" if change > 0.5 else f", down {abs(change):.0f}%" if change < -0.5 else ", little changed")
    return f"{label} was {_fmt(v0, fmt)}{unit} in {y0} and {_fmt(v1, fmt)}{unit} in {y1}{direction}."


def _stats_table(area, national):
    lines = ["| Measure | Value | Period | Against the LA average |", "|---|---|---|---|"]
    for label, key, fmt, period_col in KEY_STATS:
        if area.get(key) is None:
            continue
        cmp = _compare(key, area.get(key), national.get(key)) or ""
        lines.append(f"| {label} | {_fmt(area[key], fmt)} | {area.get(period_col) or ''} | {cmp} |")
    return "\n".join(lines) if len(lines) > 2 else ""


@tool
def summarise_area(area_name: str) -> str:
    """Generate a comprehensive profile of a local authority area with charts.

    Queries mv_area_overview and mv_area_timeseries for every available metric and returns the profile as
    sections, each a heading, one or two factual sentences and a chart or map: key stats against the local
    authority average, a radar chart, population, house prices, employment, jobs and businesses, top schools
    and a crime hotspot map. The sections are shown to the user as they are. Write only a short Summary
    paragraph after this tool returns, not a restatement of the figures.

    Args:
        area_name: Name of the local authority (e.g. "Lewisham", "Buckinghamshire", "Manchester")
    """
    result = run_sql.execute_and_track(OVERVIEW_SQL, parameters={"area_name": area_name})
    if "error" in result:
        return f"Error querying data for '{area_name}': {result['error']}"
    if not result["rows"]:
        return f"No exact match for '{area_name}'. Use run_sql to search rs_dim_geography for matching names, then call summarise_area with the exact name."
    area = result["rows"][0]
    geo_name, geo_code = area.get("geography_name", area_name), area.get("geography_code")

    # The five detail queries are independent; running them together takes the time of the slowest
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_national = pool.submit(_rows, NATIONAL_SQL)
        f_ts = pool.submit(_rows, TIMESERIES_SQL, {"geography_code": geo_code})
        f_hpi = pool.submit(_rows, HPI_SQL, {"geography_code": geo_code})
        f_crime = pool.submit(_rows, CRIME_SQL, {"geography_code": geo_code})
        f_schools = pool.submit(_rows, SCHOOLS_SQL, {"geography_code": geo_code})
    national = (f_national.result() or [{}])[0]
    ts, hpi, crime, schools = f_ts.result(), f_hpi.result(), f_crime.result(), f_schools.result()

    sections = [f"## {geo_name}"]

    table = _stats_table(area, national)
    if table:
        sections += ["### Key figures", "Each figure is the latest available, from the period shown.", table]

    sections += ["### How it compares", f"Eight measures scored 0 to 100 against the {AVERAGE_LABEL}; further out is better.", _radar(geo_name, area, national)]

    pop = [r for r in ts if r.get("total_population") is not None]
    if len(pop) >= 3:
        sections += ["### Population", _trend_sentence("The population", pop, "total_population", "{:,.0f}"), _chart({
            "type": "bar",
            "data": {"labels": [str(r["calendar_year"]) for r in pop], "datasets": [{"label": "Population", "data": [r["total_population"] for r in pop], "backgroundColor": BLUE}]},
            "options": {"responsive": True, "plugins": {"title": {"display": True, "text": f"{geo_name}: population over time"}, "legend": {"display": False}}},
        })]
    if len(hpi) >= 3:
        chart = _line(f"{geo_name}: House Price Index (ONS)", [str(r["calendar_year"]) for r in hpi],
                      [("Average price (£)", [r["avg_price"] for r in hpi], BLUE, "y"), ("Annual change (%)", [r["annual_change_pct"] for r in hpi], GREEN, "y1")],
                      {"y": "Average price (£)", "y1": "Annual change (%)"})
        sections += ["### House prices", _trend_sentence("The average house price", hpi, "avg_price", "£{:,.0f}"), chart]
    emp = [r for r in ts if r.get("employment_rate") is not None or r.get("unemployment_rate") is not None]
    if len(emp) >= 3:
        chart = _line(f"{geo_name}: employment and unemployment over time", [str(r["calendar_year"]) for r in emp],
                      [("Employment rate (%)", [r["employment_rate"] for r in emp], BLUE, "y"), ("Unemployment rate (%)", [r["unemployment_rate"] for r in emp], RED, "y1")],
                      {"y": "Employment rate (%)", "y1": "Unemployment rate (%)"})
        if chart:
            sentence = " ".join(x for x in [_trend_sentence("The employment rate", emp, "employment_rate", "{:.1f}", "%"), _trend_sentence("Unemployment", emp, "unemployment_rate", "{:.1f}", "%")] if x)
            sections += ["### Employment", sentence, chart]
    econ = [r for r in ts if r.get("total_jobs") is not None or r.get("active_enterprises") is not None]
    if len(econ) >= 3:
        chart = _line(f"{geo_name}: jobs and businesses over time", [str(r["calendar_year"]) for r in econ],
                      [("Total jobs", [r["total_jobs"] for r in econ], BLUE, "y"), ("Active enterprises", [r["active_enterprises"] for r in econ], GREEN, "y1")],
                      {"y": "Total jobs", "y1": "Active enterprises"})
        if chart:
            sentence = " ".join(x for x in [_trend_sentence("Jobs", econ, "total_jobs", "{:,.0f}"), _trend_sentence("Active enterprises", econ, "active_enterprises", "{:,.0f}")] if x)
            sections += ["### Jobs and businesses", sentence, chart]
    if schools:
        top = schools[0]
        sections += ["### Schools", f"{len(schools)} schools shown by Attainment 8 in the latest year; the highest is {top.get('school_name') or 'unnamed'} at {_fmt(top['attainment8_average'], '{:.1f}')}.", _chart({
            "type": "bar",
            "data": {"labels": [(r.get("school_name") or "Unknown")[:25] for r in schools],
                     "datasets": [{"label": "Attainment 8", "data": [round(float(r["attainment8_average"]), 1) for r in schools], "backgroundColor": BLUE}]},
            "options": {"responsive": True, "indexAxis": "y", "plugins": {"title": {"display": True, "text": f"{geo_name}: top schools (Attainment 8)"}, "legend": {"display": False}}},
        })]
    points = [{"name": r.get("street_name") or "Unknown", "lat": r["avg_latitude"], "lng": r["avg_longitude"], "value": r["crimes"], "label": f"{r['crimes']} crimes"}
              for r in crime if r.get("avg_latitude") and r.get("avg_longitude")]
    if points:
        sections += ["### Crime", f"The {len(points)} streets with the most recorded crimes, {area.get('crime_period') or 'latest period'}; the highest is {points[0]['name']} with {points[0]['value']:,}.", json.dumps({"__map__": True, "config": {"title": f"{geo_name}: crime hotspots", "points": points}})]

    return "\n".join(x for x in sections if x)

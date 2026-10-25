"""AgentCore Gateway tool summarise_area: a local authority profile as JSON, the same queries and comparisons as agent-shared-tools/summarise_area.py."""
import logging
import os
import time

import boto3

import redshift_data
import registry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TRACKING_TABLE = os.environ["DATASET_TRACKING_TABLE"]
dynamodb = boto3.resource("dynamodb")

# Every table the profile reads; the two views count every source that feeds them
TABLES_READ = {"mv_area_overview", "mv_area_timeseries", "rs_fact_crime", "rs_fact_school_detail", "rs_fact_hpi"}

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
    SELECT calendar_year, total_population, median_weekly_pay,
           median_house_price, claimant_count, uc_claimants, hb_claimants,
           children_low_income, pip_claimants,
           employment_rate, unemployment_rate, total_crimes,
           total_jobs, active_enterprises, total_gva,
           total_service_spend_k
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

# (label, overview column, scale low, scale high, lower is better)
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


def _compare(key, area_val, nat_val):
    """similar, above, below, better or worse than the local authority average, or None when either side is missing or not numeric."""
    if area_val is None or nat_val is None:
        return None
    try:
        a, n = float(area_val), float(nat_val)
    except (ValueError, TypeError):
        return None
    if n == 0 or abs(a - n) / abs(n) * 100 < 3:
        return "similar"
    if key in LOWER_IS_BETTER:
        return "better" if a < n else "worse"
    return "above" if a > n else "below"


def _radar(area, national):
    """Area and national scores normalised to 0-100 per RADAR_METRICS, inverted where lower is better."""
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
    return {"labels": labels, "area": area_scores, "la_average": nat_scores}


def _track_tables(query_id):
    """Record the tables the profile read, for the usage dashboard; a failure here never fails the profile."""
    try:
        ts = int(time.time())
        with dynamodb.Table(TRACKING_TABLE).batch_writer() as batch:
            for t in TABLES_READ:
                batch.put_item(Item={"query_id": query_id, "table_name": t, "queried_at": ts, "ttl": ts + 86400 * 30})
    except Exception:
        logger.exception("Failed to track tables for %s", query_id)


def _attribution():
    """Statements for every source the profile draws on; a registry failure never fails the profile."""
    try:
        return registry.statements(registry.sources_for(TABLES_READ))
    except Exception:
        logger.exception("Failed to read the registry for attribution")
        return []


def handler(event, context):
    arguments = event.get("arguments", event)
    area_name = str(arguments.get("area_name", "")).strip()
    if not area_name:
        return {"error": "Missing required parameter: area_name"}

    try:
        _, rows = redshift_data.run(OVERVIEW_SQL, context, parameters={"area_name": area_name})
        if not rows:
            return {"error": f"No match for '{area_name}'. Search rs_dim_geography for similar names with query_data."}
        area = rows[0]
        geo_code = area["geography_code"]
        national = redshift_data.run(NATIONAL_SQL, context)[1][0]
        timeseries = redshift_data.run(TIMESERIES_SQL, context, parameters={"geography_code": geo_code})[1]
        hpi = redshift_data.run(HPI_SQL, context, parameters={"geography_code": geo_code})[1]
        crime = redshift_data.run(CRIME_SQL, context, parameters={"geography_code": geo_code})[1]
        schools = redshift_data.run(SCHOOLS_SQL, context, parameters={"geography_code": geo_code})[1]
    except redshift_data.QueryError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("summarise_area failed for %s", area_name)
        return {"error": f"The profile for '{area_name}' could not be built, try again."}

    _track_tables(context.aws_request_id)
    comparisons = {k: c for k, v in area.items() if (c := _compare(k, v, national.get(k)))}
    return {
        "area": area,
        "national_averages": national,
        "comparisons": comparisons,
        "radar": _radar(area, national),
        "timeseries": timeseries,
        "hpi": hpi,
        "crime_hotspots": [r for r in crime if r.get("avg_latitude") and r.get("avg_longitude")],
        "top_schools": schools,
        "attribution": _attribution(),
    }

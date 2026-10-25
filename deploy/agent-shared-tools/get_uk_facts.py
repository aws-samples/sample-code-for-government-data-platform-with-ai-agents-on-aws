"""Returns the national headline figures from mv_uk_summary as one table."""
from strands import tool
from . import run_sql

# (label, value column, year or period column, prefix, suffix)
_ROWS = [
    ("Population (UK)", "total_population", "population_year", "", ""),
    ("Median weekly pay", "median_weekly_pay", "earnings_year", "£", ""),
    ("Life satisfaction (out of 10)", "life_satisfaction", "wellbeing_year", "", ""),
    ("Happiness (out of 10)", "happiness", "wellbeing_year", "", ""),
    ("Anxiety (out of 10)", "anxiety", "wellbeing_year", "", ""),
    ("Average house price", "median_house_price", "house_prices_year", "£", ""),
    ("Property transactions", "total_transactions", "house_prices_year", "", ""),
    ("IMD deprivation score (average of areas, England)", "avg_imd_score", None, "", ""),
    ("Neighbourhoods in the most deprived decile (average %, England)", "pct_most_deprived", None, "", "%"),
    ("Universal Credit claimants", "total_uc_claimants", "uc_period", "", ""),
    ("Children in low income families", "total_children_low_income", "children_low_income_period", "", ""),
    ("PIP claimants", "total_pip_claimants", "pip_period", "", ""),
    ("Claimant count", "total_claimant_count", "claimant_count_year", "", ""),
    ("Employment rate", "employment_rate", None, "", "%"),
    ("Unemployment rate", "unemployment_rate", None, "", "%"),
    ("Recorded crimes", "total_crimes", "crime_year", "", ""),
    ("Average Attainment 8 (schools, England)", "avg_attainment_8", "school_year", "", ""),
]


def _fmt(val, prefix="", suffix=""):
    if val is None:
        return "Data not available"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return f"{prefix}{val}{suffix}"
    return f"{prefix}{num:,.0f}{suffix}" if num > 1000 or num == int(num) else f"{prefix}{num:.1f}{suffix}"


@tool
def get_uk_facts() -> str:
    """Get the national headline statistics: population, earnings, wellbeing, house prices, deprivation, benefits, employment, crime and school performance, each with the year or period it is from."""
    result = run_sql.execute_and_track("SELECT * FROM mv_uk_summary LIMIT 1")
    if "error" in result:
        return f"Error: {result['error']}"
    row = result["rows"][0] if result["rows"] else {}
    lines = ["## National summary", "", "| Metric | Value | Data year |", "|---|---|---|"]
    for label, col, period_col, prefix, suffix in _ROWS:
        period = row.get(period_col) if period_col else None
        lines.append(f"| {label} | {_fmt(row.get(col), prefix, suffix)} | {period if period is not None else 'latest'} |")
    return "\n".join(lines)

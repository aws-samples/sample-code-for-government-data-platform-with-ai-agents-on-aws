"""Every gold table, in build order, with the registry entry, attribution and data agent prompt notes for its source. Plain Python only; the data review and the data agent import it without Spark."""

MONTH_LABEL = "CAST(date_format(to_date({col}, 'MMMM yyyy'), 'yyyyMM') AS INT) AS period_yyyymm"
ACADEMIC_YEAR_END = "CAST(SUBSTRING(time_period, 1, 4) AS INT) + 1 AS calendar_year"

# Provider-specified attribution statements, or the licence's default sentence where there is none; {year} is filled in where shown
OGL_STATEMENT = "Contains public sector information licensed under the Open Government Licence v3.0"
ONS_STATEMENT = "Source: Office for National Statistics licensed under the Open Government Licence v.3.0"
OS_STATEMENT = "Contains OS data © Crown copyright and database right {year}"
ROYAL_MAIL_STATEMENT = "Contains Royal Mail data © Royal Mail copyright and database right {year}"
HMLR_STATEMENT = "Contains HM Land Registry data © Crown copyright and database right {year}. This data is licensed under the Open Government Licence v3.0."

OGL = [OGL_STATEMENT]
ONS = [ONS_STATEMENT]
HMLR = [HMLR_STATEMENT]

TABLES = [
    # Dimensions. The first two must build or the job stops.
    {
        "gold_table": "dim_geography", "build": "dim_geography", "required": True,
        "source_id": "ons-geography", "department": "ONS", "name": "ONS Open Geography Portal: council boundaries, centroids, postcode and code lookups",
        "api_url": "https://geoportal.statistics.gov.uk/", "attribution": [ONS_STATEMENT, OS_STATEMENT, ROYAL_MAIL_STATEMENT],
        "update_frequency": "on-demand", "bronze_s3_prefix": "bronze/ons/geography/", "glue_job_name": "bronze-to-silver-ons-geography",
        "prompt": (
            "Column details: geography_code (PK, e.g. E07000217).\n"
            "geography_type values: local_authority, ni_district, scottish_council.\n"
            "Use for name→code lookups and coordinates. JOIN to fact tables on geography_code."
        ),
    },
    {
        "gold_table": "dim_time", "build": "dim_time", "required": True,
        "prompt": (
            "Column details: period_yyyymm (PK, INT e.g. 202603); display_label (e.g. \"March 2026\").\n"
            "Month-grain calendar spine (one row per month). fiscal_year is the UK financial year ENDING year (March 2026 -> 2026).\n"
            "period_yyyymm is the canonical cross-source monthly join key, all monthly fact tables carry it. To compare monthly facts (e.g. UC vs Housing Benefit), JOIN on period_yyyymm, never on date_name (formats differ per source). Use display_label for user-facing period strings."
        ),
    },
    {
        "gold_table": "dim_region_mapping", "silver_table": "lad_to_region",
        "columns": ["geography_code", "geography_name", "region_code", "region_name"],
        "prompt": (
            "Maps English LAs to the 9 English regions (e.g. South East, West Midlands). JOIN on geography_code.\n"
            "For London or outside London, filter region_name = 'London' here; never list London boroughs by name.\n"
            "IMPORTANT: Welsh and Scottish councils have no row. An INNER JOIN silently drops them, so a \"regions\" or \"outside London\" answer becomes England-only. Either say the ranking is England-only, or LEFT JOIN and label the NULL group \"Wales and Scotland\".\n"
            "There is no coastal, rural, urban or city flag anywhere. If asked, say so and offer a proxy the user can accept (a named list of councils, or latitude/longitude), never a name-pattern guess."
        ),
    },
    # Facts
    {
        "gold_table": "fact_crime", "build": "crime", "partition": "calendar_year",
        "source_id": "police-crime", "attribution": OGL, "department": "Home Office", "name": "UK Police API: Crime Data", "api_url": "https://data.police.uk/api/",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/police/crime/", "glue_job_name": "bronze-to-silver-police-crime",
        "view_columns": {"mv_area_overview": ["total_crimes", "crime_rate_per_1000"], "mv_area_timeseries": ["total_crimes"]},
        "prompt": (
            "Column details: month (YYYY-MM).\n"
            "category values include: anti-social-behaviour, burglary, criminal-damage-arson, drugs, other-theft, public-order, robbery, shoplifting, vehicle-crime, violent-crime, other-crime.\n"
            "IMPORTANT: The most recent month often has incomplete data (Police API lag). Always exclude the latest month from comparisons, use WHERE month < (SELECT MAX(month) FROM rs_fact_crime).\n"
            "Only the latest 12 months are loaded (see the year range above), so there is no earlier year to compare against. If asked for a year-on-year change, say that plainly and offer what the data supports: a ranking for the period, or a month-to-month trend. Recorded crime is seasonal, so never compare different months of the year as if like-for-like.\n"
            "Greater Manchester Police does not publish to the Police API, so Manchester, Salford, Bolton and the other GM boroughs show near-zero crime. Exclude them from crime rankings and say why."
        ),
    },
    {
        "gold_table": "fact_population", "silver_table": "population", "partition": "calendar_year",
        "columns": ["geography_code", "sex", "age", "CAST(calendar_year AS INT) AS calendar_year", "population"],
        "source_id": "ons-population", "attribution": ONS, "department": "ONS", "name": "ONS Mid-Year Population Estimates", "api_url": "https://www.nomisweb.co.uk/api/v01/dataset/NM_2002_1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/ons/population/", "glue_job_name": "bronze-to-silver-ons-population",
        "view_columns": {"mv_area_overview": ["total_population"], "mv_area_timeseries": ["total_population"]},
        "prompt": (
            "No geography_name, JOIN to rs_dim_geography for names.\n"
            "age is text: individual years '0' to '89', '90+', AND a summary 'Total' row.\n"
            "sex values: 'All', 'Male', 'Female' (yes, 'All' is in addition to Male/Female).\n"
            "IMPORTANT: For total population use WHERE sex = 'All' AND age = 'Total' (one row per area-year). Never SUM across all rows without these filters, you'll over-count by ~6x (All + Male + Female x individual ages + Total).\n"
            "geography_code covers several levels that overlap: local authorities, counties, regions, countries, England and Wales (K04000001), Great Britain (K03000001) and the UK (K02000001).\n"
            "For a national total, select that single row, e.g. geography_code = 'K04000001'. Never SUM across geography codes.\n"
            "To total a set of local authorities, JOIN rs_dim_geography and filter geography_type = 'local_authority'."
        ),
    },
    {
        "gold_table": "fact_wellbeing", "silver_table": "wellbeing", "partition": "calendar_year",
        "columns": ["geography_code", "measure_name AS measure", "estimate_name AS estimate",
                    "CAST(SUBSTRING(period, 1, 4) AS INT) AS calendar_year", "period", "value", "lower_limit", "upper_limit"],
        "source_id": "ons-wellbeing", "attribution": ONS, "department": "ONS", "name": "ONS Personal Well-being", "api_url": "https://api.beta.ons.gov.uk/v1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/ons/wellbeing/", "glue_job_name": "bronze-to-silver-ons-wellbeing",
        "view_columns": {"mv_area_overview": ["life_satisfaction", "happiness", "anxiety"], "mv_area_timeseries": ["life_satisfaction"]},
        "prompt": (
            "No geography_name, JOIN to rs_dim_geography for names.\n"
            "measure values: Anxiety, Happiness, Life satisfaction, Worthwhile.\n"
            "estimate values: Average (mean), Fair, Good, Poor, Very good.\n"
            "For typical queries use estimate = 'Average (mean)'.\n"
            "period is the survey year, e.g. '2022-23'; calendar_year is its start year. ONS last updated this API dataset in 2023 and it ends at 2022-23. Say that when quoting it."
        ),
    },
    {
        "gold_table": "fact_earnings", "silver_table": "earnings", "partition": "calendar_year", "filter": "value IS NOT NULL",
        "columns": ["geography_code", "sex", "working_pattern", "measure", "percentile", "workplace_residence",
                    "CAST(calendar_year AS INT) AS calendar_year", "value", "coefficient_of_variation"],
        "source_id": "ons-earnings", "attribution": ONS, "department": "ONS", "name": "ONS Earnings (ASHE Tables 7 & 8)", "api_url": "https://api.beta.ons.gov.uk/v1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/ons/earnings/", "glue_job_name": "bronze-to-silver-ons-earnings",
        "view_columns": {"mv_area_overview": ["median_weekly_pay"], "mv_area_timeseries": ["median_weekly_pay"]},
        "prompt": (
            "ASHE, annual from 2014. No geography_name, JOIN to rs_dim_geography for names.\n"
            "geography_code covers councils, counties, regions (E12), England (E92000001), Scotland (S92000003), England and Wales (K04000001) and Great Britain (K02000001, K03000001). For a national figure select that single row; never average councils.\n"
            "Councils merged in 2023 (e.g. Somerset, North Yorkshire, Cumberland) appear under their old district codes before 2023, which aren't in rs_dim_geography. Medians can't be combined. Say that if asked for their history.\n"
            "measure values: Annual pay - Gross, Hourly pay - Gross, Weekly pay - Gross, Overtime pay, etc.\n"
            "working_pattern: All, Full-Time, Part-Time.\n"
            "workplace_residence: Residence, Workplace.\n"
            "sex: All, Male, Female.\n"
            "percentile: Median, Mean, 10th percentile, 25th percentile, 30th percentile, 40th percentile, 60th percentile, 70th percentile, 75th percentile, 80th percentile, 90th percentile.\n"
            "Default query: measure='Annual pay - Gross', working_pattern='Full-Time', workplace_residence='Residence', sex='All', percentile='Median'.\n"
            "The views' median_weekly_pay is a different slice: Workplace-based, all working patterns. It measures jobs located in the area, not what residents earn, and is inflated in commuter destinations (Slough, Crawley, Coventry). For where-to-live, affordability or price-to-earnings questions use the Residence default from this table, and say which basis you used."
        ),
    },
    {
        "gold_table": "fact_school_performance", "build": "school_performance", "partition": "calendar_year",
        "source_id": "dfe-school-performance", "attribution": OGL, "department": "DfE", "name": "DfE KS4 School Performance", "api_url": "https://api.education.gov.uk/statistics/v1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/dfe/school-performance/", "glue_job_name": "bronze-to-silver-dfe-school-performance",
        "view_columns": {"mv_area_overview": ["avg_attainment_8"]},
        "prompt": (
            "Column details: t_cohort (pupils); avg_att8 (Attainment 8); pt_l2basics_95 (% grade 4+ / 5+ in English and maths).\n"
            "KS4 results for each education authority (councils and county councils), plus England as geography_code 'E92000001'. Annual time series.\n"
            "calendar_year is the year the academic year ends: time_period 202425 is academic year 2024/25, calendar_year 2025, results from summer 2025.\n"
            "version: Final, Revised or Provisional. The latest year is often Provisional. Say that when quoting it.\n"
            "2019/20 and 2020/21 (calendar_year 2020 and 2021) used teacher-assessed grades during the pandemic; their scores are higher and aren't comparable with exam years. Say that when a trend crosses them.\n"
            "One row per area, year and breakdown. For the headline figure use breakdown_topic = 'Total' (one row per area-year). For a breakdown, filter breakdown_topic to it, e.g. 'Sex' with gender IN ('Boys', 'Girls'), 'Disadvantage status', 'FSM status', 'SEN provision', 'SEN primary need', 'Ethnicity', 'First language', 'KS2 scaled score group' (prior attainment, with prior_attainment giving the High, Mid or Low band), 'Mobility', 'Young carer', 'School admission type', 'School religious character', or combinations such as 'Sex by ethnicity'. The other characteristic columns read 'Total' on those rows. Never average across rows.\n"
            "NOTE: District councils have no entry. Secondary education is reported under the county council. Use rs_fact_school_detail for individual school lookups within a district."
        ),
    },
    {
        "gold_table": "fact_house_prices", "build": "house_prices", "partition": "calendar_year",
        "source_id": "land-registry", "attribution": HMLR, "department": "HM Land Registry", "name": "HM Land Registry Price Paid",
        "api_url": "https://s3.eu-west-1.amazonaws.com/prod1.publicdata.landregistry.gov.uk/",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/land-registry/price-paid/", "glue_job_name": "bronze-to-silver-land-registry-price-paid",
        "view_columns": {"mv_area_overview": ["median_house_price", "total_transactions"], "mv_area_timeseries": ["median_house_price"]},
        "prompt": (
            "No geography_name, JOIN to rs_dim_geography for names.\n"
            "property_type values: D (Detached), S (Semi-detached), T (Terraced), F (Flat/Maisonette), O (Other).\n"
            "duration: F (Freehold), L (Leasehold), U (Unknown, a few hundred sales).\n"
            "old_new: Y (New build), N (Existing)."
        ),
    },
    {
        "gold_table": "fact_school_detail", "silver_table": "school_detail", "partition": "calendar_year",
        "columns": ["school_urn", "school_name", "school_laestab", "new_la_code AS geography_code", "la_name", ACADEMIC_YEAR_END,
                    "time_period", "time_identifier", "version", "establishment_type_group", "breakdown_topic", "breakdown",
                    "sex", "disadvantage_status",
                    *[f"CAST({c} AS DOUBLE) AS {c}" for c in (
                        "pupil_count", "attainment8_average", "progress8_average", "progress8_lower_ci",
                        "progress8_upper_ci", "engmath_94_percent", "engmath_95_percent")]],
        "source_id": "dfe-school-detail", "attribution": OGL, "department": "DfE", "name": "DfE School-Level Performance Tables", "api_url": "https://api.education.gov.uk/statistics/v1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/dfe/school-detail/", "glue_job_name": "bronze-to-silver-dfe-school-detail",
        "prompt": (
            "KS4 results per school for the years DfE still publishes at school level. calendar_year is the year the academic year ends, as in rs_fact_school_performance.\n"
            "For each school's headline figure use breakdown_topic = 'Total'. breakdown_topic values: Total, Sex, Disadvantage status, First language, Mobility, Prior attainment. breakdown names the group, e.g. 'Girls', 'Disadvantaged'.\n"
            "Metrics are null where DfE suppresses them for small cohorts."
        ),
    },
    {
        "gold_table": "fact_claimant_count", "silver_table": "claimant_count", "partition": "calendar_year", "warn_null_periods": True,
        "columns": ["geography_code", "geography_name", "date_name", MONTH_LABEL.format(col="date_name"), "calendar_year", "claimant_count"],
        "source_id": "nomis-claimant-count", "attribution": ONS, "department": "ONS", "name": "NOMIS Claimant Count", "api_url": "https://www.nomisweb.co.uk/api/v01/dataset/NM_162_1",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/nomis/claimant-count/", "glue_job_name": "bronze-to-silver-nomis-claimant-count",
        "view_columns": {"mv_area_overview": ["latest_claimant_count"], "mv_area_timeseries": ["claimant_count"]},
        "prompt": (
            "date_name is text (e.g. \"January 2024\"). Use period_yyyymm for ordering and joins, because MAX(date_name) sorts alphabetically, not chronologically. No claimant_rate column."
        ),
    },
    {
        "gold_table": "fact_employment", "silver_table": "employment",
        "columns": ["geography_code", "geography_name", "date_name", "variable_name", "measures_name", "obs_value",
                    "CAST(date_format(to_date(trim(split(date_name, '-')[1]), 'MMM yyyy'), 'yyyyMM') AS INT) AS period_end_yyyymm"],
        "year": "CAST(regexp_extract(date_name, '(\\\\d{4})', 1) AS INT)", "year_end": "CAST(regexp_extract(date_name, '.*(\\\\d{4})', 1) AS INT)",
        "source_id": "ons-employment", "attribution": ONS, "department": "ONS", "name": "ONS APS Employment", "api_url": "https://www.nomisweb.co.uk/api/v01/dataset/NM_17_5",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/nomis/employment/", "glue_job_name": "bronze-to-silver-ons-employment",
        "view_columns": {"mv_area_overview": ["employment_rate", "unemployment_rate"], "mv_area_timeseries": ["employment_rate", "unemployment_rate"]},
        "prompt": (
            "Column details: date_name (text period e.g. \"Oct 2023-Sep 2024\"); period_end_yyyymm (INT, e.g. 202409).\n"
            "No calendar_year column. Rolling 12-month periods overlap. Use MAX(period_end_yyyymm) for latest, never MAX(date_name), which sorts alphabetically.\n"
            "Key variable_name values: Employment rate - aged 16-64, Unemployment rate - aged 16-64, Economic activity rate - aged 16-64, % who are economically inactive - aged 16-64, % with NVQ4+ - aged 16-64, % with no qualifications (NVQ) - aged 16-64.\n"
            "measures_name is always 'Variable'. Filter on it for clean results."
        ),
    },
    {
        "gold_table": "fact_deprivation", "build": "deprivation", "year": ("2025", "2025"),
        "source_id": "mhclg-deprivation", "attribution": OGL, "department": "MHCLG", "name": "MHCLG Index of Multiple Deprivation 2025",
        "api_url": "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025",
        "update_frequency": "on-demand", "bronze_s3_prefix": "bronze/mhclg/deprivation/", "glue_job_name": "bronze-to-silver-mhclg-deprivation",
        "view_columns": {"mv_area_overview": ["avg_imd_score", "pct_most_deprived"]},
        "prompt": (
            "One row per LA. Domain scores allow breakdown by deprivation type."
        ),
    },
    {
        "gold_table": "fact_universal_credit", "silver_table": "universal_credit", "partition": "calendar_year", "warn_null_periods": True,
        "columns": ["geography_code", "la_name", "date_name",
                    "CAST(date_format(to_date(date_name, 'MMMM yyyy'), 'yyyyMM') AS INT) AS period_yyyymm", "calendar_year", "claimant_count"],
        "source_id": "dwp-universal-credit", "attribution": OGL, "department": "DWP", "name": "DWP Universal Credit (Stat-Xplore)", "api_url": "https://stat-xplore.dwp.gov.uk/",
        "update_frequency": "quarterly", "bronze_s3_prefix": "bronze/dwp/universal-credit/", "glue_job_name": "bronze-to-silver-dwp-universal-credit",
        "view_columns": {"mv_area_overview": ["latest_uc_claimants"], "mv_area_timeseries": ["uc_claimants"]},
        "prompt": (
            "People on Universal Credit by local authority, monthly. Welsh la_name values are bilingual (e.g. \"Cardiff / Caerdydd\"): join on geography_code, not la_name. geography_code is null for the \"Unknown\" area.\n"
            "date_name is text (e.g. \"February 2026\"). Use period_yyyymm for ordering and monthly joins.\n"
            "Monthly STOCK measure: for annual figures use the latest month per year, never SUM months."
        ),
    },
    {
        "gold_table": "fact_housing_benefit", "silver_table": "housing_benefit", "partition": "calendar_year",
        "columns": ["geography_code", "la_name", "date_name", "CAST(SUBSTRING(date_name, 1, 6) AS INT) AS period_yyyymm", "calendar_year", "caseload_count"],
        "source_id": "dwp-housing-benefit", "attribution": OGL, "department": "DWP", "name": "DWP Housing Benefit (Stat-Xplore)", "api_url": "https://stat-xplore.dwp.gov.uk/",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/dwp/housing-benefit/", "glue_job_name": "bronze-to-silver-dwp-housing-benefit",
        "view_columns": {"mv_area_overview": ["latest_hb_claimants"], "mv_area_timeseries": ["hb_claimants"]},
        "prompt": (
            "Housing Benefit caseload by local authority. Being replaced by UC for working-age claimants.\n"
            "date_name is raw source format (e.g. \"202603 (Mar-26)\"), use period_yyyymm for ordering and monthly joins.\n"
            "Monthly STOCK measure: for annual figures use the latest month per year, never SUM months.\n"
            "Has geography_code (GSS code) for direct joins."
        ),
    },
    {
        "gold_table": "fact_children_low_income", "silver_table": "children_low_income", "partition": "calendar_year",
        "columns": ["geography_code", "la_name", "date_name", "calendar_year", "measure", "children_count"],
        "source_id": "dwp-cilif", "attribution": OGL, "department": "DWP", "name": "DWP Children in Low Income Families (Stat-Xplore)", "api_url": "https://stat-xplore.dwp.gov.uk/",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/dwp/cilif/", "glue_job_name": "bronze-to-silver-dwp-cilif",
        "view_columns": {"mv_area_overview": ["latest_children_low_income"], "mv_area_timeseries": ["children_low_income"]},
        "prompt": (
            "Children (under 16) in low income families (CiLIF) by local authority, annual financial years.\n"
            "date_name is the financial year (e.g. \"2024/25\"); calendar_year is the FY start year (2024).\n"
            "measure values: relative_bhc (headline, FYE 2022-2025), absolute_bhc (FYE 2022-2025), relative_ahc (FYE 2024-2025).\n"
            "ALWAYS filter on one measure, rows are per measure, summing across measures double-counts. Default measure='relative_bhc'.\n"
            "Counts only, no rates in this table (published rates use ONS child population denominators).\n"
            "Has geography_code (GSS code) for direct joins. Covers UK including Northern Ireland."
        ),
    },
    {
        "gold_table": "fact_pip", "silver_table": "pip", "partition": "calendar_year",
        "columns": ["geography_code", "la_name", "date_name", "CAST(date_name AS INT) AS period_yyyymm", "calendar_year", "caseload_count"],
        "source_id": "dwp-pip", "attribution": OGL, "department": "DWP", "name": "DWP Personal Independence Payment (Stat-Xplore)", "api_url": "https://stat-xplore.dwp.gov.uk/",
        "update_frequency": "quarterly", "bronze_s3_prefix": "bronze/dwp/pip/", "glue_job_name": "bronze-to-silver-dwp-pip",
        "view_columns": {"mv_area_overview": ["latest_pip_claimants"], "mv_area_timeseries": ["pip_claimants"]},
        "prompt": (
            "Personal Independence Payment cases with entitlement by local authority, monthly since Jan 2019.\n"
            "date_name is a sortable yyyymm string (e.g. \"202607\"), not a month name. period_yyyymm is the same value as INT.\n"
            "Monthly STOCK measure: for annual figures use the latest month per year, never SUM months.\n"
            "Has geography_code (GSS code) for direct joins. Covers GB (no Northern Ireland)."
        ),
    },
    {
        "gold_table": "fact_road_traffic", "silver_table": "road_traffic", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year",
                    "total_link_length_km", "total_link_length_miles", "cars_and_taxis", "all_motor_vehicles"],
        "merge_measures": ["total_link_length_km", "total_link_length_miles", "cars_and_taxis", "all_motor_vehicles"],
        "source_id": "dft-road-traffic", "attribution": OGL, "department": "DfT", "name": "DfT Road Traffic Statistics", "api_url": "https://roadtraffic.dft.gov.uk/api/",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/dft/road-traffic/", "glue_job_name": "bronze-to-silver-dft-road-traffic",
        "view_columns": {"mv_area_overview": ["all_motor_vehicles"], "mv_area_timeseries": ["all_motor_vehicles"]},
        "prompt": (
            "Vehicle counts are annual totals. No per-vehicle-type breakdown beyond cars_and_taxis vs all."
        ),
    },
    {
        "gold_table": "fact_gva", "silver_table": "gva", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year", "sic_code", "industry", "price_type", "gva_value"],
        # Only current prices add up across areas; chained volume measures and indices keep the old code
        "merge_measures": ["gva_value"], "merge_where": "price_type = 'Current prices'",
        "source_id": "ons-gva", "attribution": ONS, "department": "ONS", "name": "ONS GVA by Industry by Local Authority", "api_url": "https://api.beta.ons.gov.uk/v1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/ons/gva/", "glue_job_name": "bronze-to-silver-ons-gva",
        "view_columns": {"mv_area_overview": ["total_gva"], "mv_area_timeseries": ["total_gva"]},
        "prompt": (
            "Rows are per-industry. For total GVA use sic_code='total'. Do NOT SUM across rows.\n"
            "price_type values: Current prices, Chained volume measures in 2016 money value, Chained volume measures index, Implied deflator.\n"
            "Default: price_type='Current prices', sic_code='total'. The index is 100 in 2016 and is only meaningful for sic_code='total'; for a small industry in a small area it can be in the thousands.\n"
            "gva_value is in £ millions (Birmingham 2018 total is 29,079, i.e. £29.1bn). Multiply by 1,000,000 before dividing by population for GVA per head.\n"
            "This API dataset ends at 2018 and ONS last refreshed it in 2021. Say that when quoting it; do not say ONS stopped publishing local GVA."
        ),
    },
    {
        "gold_table": "fact_trade", "silver_table": "trade", "partition": "calendar_year",
        "columns": ["month_id", "CAST(month_id AS INT) AS period_yyyymm", "CAST(calendar_year AS INT) AS calendar_year", "CAST(month AS INT) AS month",
                    "region_name", "region_group", "CAST(region_id AS INT) AS region_id", "country_name", "country_code", "flow_type",
                    "CAST(sitc2_id AS INT) AS sitc2_id", "trade_value", "net_mass_kg"],
        "source_id": "hmrc-trade", "attribution": OGL, "department": "HMRC", "name": "HMRC UK Trade Info: Regional Trade Statistics", "api_url": "https://api.uktradeinfo.com/RTS",
        "update_frequency": "quarterly", "bronze_s3_prefix": "bronze/hmrc/trade/", "glue_job_name": "bronze-to-silver-hmrc-trade",
        "prompt": (
            "NOTE: by UK region, not LA. No geography_code. HMRC's Regional Trade Statistics API covers trade with non-EU countries only; flow_type values are 'Non-EU Exports' and 'Non-EU Imports'. Say that when quoting a total. trade_value is in pounds. Quarterly: month is 1, 4, 7 or 10, each row covering the quarter that starts then. period_yyyymm equals month_id.\n"
            "Always filter or GROUP BY flow_type. A SUM without it adds exports and imports together and must not be called \"exports\". Growth over several years is in nominal pounds; say so."
        ),
    },
    {
        "gold_table": "fact_aps", "silver_table": "aps", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "date_name", "calendar_year", "variable_name", "measures_name", "obs_value"],
        "source_id": "nomis-aps", "attribution": ONS, "department": "ONS", "name": "NOMIS Annual Population Survey", "api_url": "https://www.nomisweb.co.uk/api/v01/dataset/NM_17_5",
        "update_frequency": "quarterly", "bronze_s3_prefix": "bronze/nomis/aps/", "glue_job_name": "bronze-to-silver-nomis-aps",
        "view_columns": {"mv_area_overview": ["econ_activity_rate", "pct_nvq4_plus", "pct_no_qualifications"],
                         "mv_area_timeseries": ["econ_activity_rate", "pct_nvq4_plus"]},
        "prompt": (
            "Annual Population Survey, qualification and employment breakdowns by age/sex."
        ),
    },
    {
        "gold_table": "nhs_rtt_waiting_times", "rs_table": "rs_fact_nhs_rtt", "silver_table": "nhs_rtt_waiting_times",
        "partition": "calendar_year", "warn_null_periods": True,
        "columns": ["CAST(calendar_year AS INT) AS calendar_year", "month_name",
                    MONTH_LABEL.format(col="concat(month_name, ' ', CAST(calendar_year AS STRING))"),
                    "commissioner_org_code", "commissioner_org_name", "commissioner_parent_org_code", "commissioner_parent_name",
                    "total_waiting", "waiting_over_18_weeks", "waiting_over_52_weeks", "pct_over_18_weeks"],
        "source_id": "nhs-rtt-waiting-times", "attribution": OGL, "department": "NHS England", "name": "NHS England RTT Waiting Times",
        "api_url": "https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/nhs/rtt-waiting-times/", "glue_job_name": "bronze-to-silver-nhs-rtt",
        "prompt": (
            "NOTE: by NHS commissioner/ICB, not LA."
        ),
    },
    {
        "gold_table": "fact_hpi", "silver_table": "hpi", "partition": "calendar_year", "filter": "geography_code IS NOT NULL",
        "columns": ["geography_code", "geography_name", "date", "calendar_year", "calendar_month",
                    "CAST(calendar_year * 100 + calendar_month AS INT) AS period_yyyymm",
                    "average_price", "monthly_change_pct", "annual_change_pct", "average_price_sa"],
        "source_id": "ons-hpi", "attribution": [HMLR_STATEMENT, ONS_STATEMENT], "department": "ONS", "name": "ONS/Land Registry UK House Price Index",
        "api_url": "https://www.gov.uk/government/collections/uk-house-price-index-reports",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/ons/hpi/", "glue_job_name": "bronze-to-silver-ons-hpi",
        "prompt": (
            "Monthly House Price Index data."
        ),
    },
    {
        "gold_table": "fact_nhs_ods", "silver_table": "nhs_ods_organisations", "partition": "snapshot_date", "year": "SUBSTRING(snapshot_date, 1, 4)",
        "columns": ["org_id", "org_name", "status", "primary_role_id", "primary_role_description", "org_type", "postcode",
                    "last_change_date", "geography_code", "geography_name", "snapshot_date"],
        "source_id": "nhs-ods", "attribution": OGL, "department": "NHS England", "name": "NHS ODS: GP Practices, Pharmacies and NHS Trusts",
        "api_url": "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations",
        "update_frequency": "monthly", "bronze_s3_prefix": "bronze/nhs/ods/", "glue_job_name": "bronze-to-silver-nhs-ods",
        "view_columns": {"mv_area_overview": ["gp_practice_count", "pharmacy_count"]},
        "prompt": (
            "Column details: geography_name (often NULL).\n"
            "org_type values: gp-practices, pharmacies, nhs-trusts.\n"
            "IMPORTANT: geography_name is NULL in this table. Always JOIN to rs_dim_geography on geography_code to get area names.\n"
            "For postcode searches: WHERE postcode LIKE 'GU22%'. Postcode-to-LA mapping may not cover all areas.\n"
            "Filter status='Active' for current organisations."
        ),
    },
    {
        "gold_table": "fact_air_quality", "silver_table": "air_quality", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year", "pm25_total", "pm25_non_anthropogenic", "pm25_anthropogenic"],
        "source_id": "defra-air-quality", "attribution": OGL, "department": "DEFRA", "name": "DEFRA UK-AIR Population-Weighted PM2.5", "api_url": "https://uk-air.defra.gov.uk/data/pcm-data",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/defra/air-quality/", "glue_job_name": "bronze-to-silver-defra-air-quality",
        "view_columns": {"mv_area_overview": ["pm25_total", "pm25_anthropogenic"], "mv_area_timeseries": ["pm25_total"]},
    },
    {
        "gold_table": "fact_la_spending", "silver_table": "la_spending", "partition": "calendar_year",
        "columns": ["geography_code", "la_name", "la_class", "CAST(calendar_year AS INT) AS calendar_year", "CAST(financial_year_start AS INT) AS financial_year_start",
                    "education_net_exp", "childrens_social_care_net_exp", "adult_social_care_net_exp", "public_health_net_exp", "housing_net_exp",
                    "cultural_net_exp", "environment_net_exp", "planning_net_exp", "transport_net_exp", "police_net_exp", "fire_rescue_net_exp",
                    "central_net_exp", "other_net_exp", "total_service_net_exp"],
        "source_id": "mhclg-spending", "attribution": OGL, "department": "MHCLG", "name": "MHCLG Revenue Outturn: LA Spending by Service",
        "api_url": "https://www.gov.uk/government/statistics/local-authority-revenue-expenditure-and-financing-england-revenue-outturn-multi-year-data-set",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/mhclg/spending/", "glue_job_name": "bronze-to-silver-mhclg-spending",
        "view_columns": {"mv_area_overview": ["total_service_spend_k", "adult_social_care_spend_k"], "mv_area_timeseries": ["total_service_spend_k"]},
        "prompt": (
            "No geography_name, use la_name. Each column is a service area in £thousands.\n"
            "IMPORTANT: District councils (e.g. Cheltenham, Stratford-on-Avon) show £0 for education, social care, and public health because those services are delivered by the county council. Only unitary authorities and metropolitan boroughs have full spending data. When comparing spending, note this two-tier structure."
        ),
    },
    {
        "gold_table": "fact_jobs_density", "silver_table": "jobs_density", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year", "total_jobs", "jobs_density"],
        "source_id": "jobs-density", "attribution": ONS, "department": "ONS", "name": "NOMIS Jobs Density", "api_url": "https://www.nomisweb.co.uk/datasets/jd",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/nomis/jobs-density/", "glue_job_name": "bronze-to-silver-jobs-density",
        "view_columns": {"mv_area_overview": ["total_jobs", "jobs_density"], "mv_area_timeseries": ["total_jobs"]},
    },
    {
        "gold_table": "fact_business_counts", "silver_table": "business_counts", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year", "active_enterprises"],
        "source_id": "business-counts", "attribution": ONS, "department": "ONS", "name": "NOMIS UK Business Counts", "api_url": "https://www.nomisweb.co.uk/datasets/idbrent",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/nomis/business-counts/", "glue_job_name": "bronze-to-silver-business-counts",
        "view_columns": {"mv_area_overview": ["active_enterprises"], "mv_area_timeseries": ["active_enterprises"]},
    },
    {
        "gold_table": "fact_births_deaths", "silver_table": "births_deaths", "partition": "calendar_year",
        "columns": ["geography_code", "geography_name", "CAST(calendar_year AS INT) AS calendar_year", "live_births", "deaths"],
        "source_id": "ons-births-deaths", "attribution": ONS, "department": "ONS", "name": "ONS Births & Deaths (NOMIS)", "api_url": "https://www.nomisweb.co.uk/api/v01/dataset/NM_205_1",
        "update_frequency": "annual", "bronze_s3_prefix": "bronze/ons/births-deaths/", "glue_job_name": "bronze-to-silver-ons-births-deaths",
        "view_columns": {"mv_area_overview": ["live_births", "deaths"], "mv_area_timeseries": ["live_births", "deaths"]},
    },
]


def rs_table(spec):
    """The Redshift copy of a gold table."""
    return spec.get("rs_table", f"rs_{spec['gold_table']}")


def by_gold_table(name):
    return next(t for t in TABLES if t["gold_table"] == name)


def by_glue_job(job_suffix):
    """The spec whose silver job is `bronze-to-silver-<x>`, or None."""
    return next((t for t in TABLES if t.get("glue_job_name") == job_suffix), None)

-- Headline national figures for England and Wales, aggregated from the rs_* objects
-- Population: sex='All' to avoid counting male+female+all
-- Earnings: median of medians (approximate), filtered to All workers
DROP MATERIALIZED VIEW IF EXISTS mv_uk_summary;

CREATE MATERIALIZED VIEW mv_uk_summary AS
SELECT
    pop.latest_year         AS population_year,
    pop.total_population,
    earn.latest_year        AS earnings_year,
    earn.median_weekly_pay,
    wb.latest_year          AS wellbeing_year,
    wb.life_satisfaction,
    wb.happiness,
    wb.anxiety,
    hp.latest_year          AS house_prices_year,
    hp.median_house_price,
    hp.total_transactions,
    dep.avg_imd_score,
    dep.pct_most_deprived,
    uc.latest_period        AS uc_period,
    uc.total_uc_claimants,
    cilif.latest_period     AS children_low_income_period,
    cilif.total_children_low_income,
    pip.latest_period       AS pip_period,
    pip.total_pip_claimants,
    cc.latest_year          AS claimant_count_year,
    cc.total_claimant_count,
    emp.employment_rate,
    emp.unemployment_rate,
    cr.latest_year          AS crime_year,
    cr.total_crimes,
    sch.latest_year         AS school_year,
    sch.avg_attainment_8
FROM
-- Population: the K04 (England and Wales) aggregate row, no SUM needed
-- Summing across all geography codes double-counts (districts inside counties inside regions)
-- Every block aggregates; an empty source gives one row of nulls and the CROSS JOINs still return a row
(
    SELECT MAX(calendar_year) AS latest_year,
           MAX(population) AS total_population
    FROM rs_fact_population
    WHERE geography_code = 'K04000001'
      AND sex = 'All'
      AND age = 'Total'
      AND calendar_year = (SELECT MAX(calendar_year) FROM rs_fact_population)
) pop
CROSS JOIN
-- Earnings: median weekly pay, all workers
(
    SELECT MAX(calendar_year) AS latest_year,
           MEDIAN(value) AS median_weekly_pay
    FROM rs_fact_earnings
    WHERE percentile = 'Median' AND sex = 'All' AND working_pattern = 'All'
      AND measure = 'Weekly pay - Gross' AND workplace_residence = 'Workplace'
      AND calendar_year = (SELECT MAX(calendar_year) FROM rs_fact_earnings)
) earn
CROSS JOIN
-- Wellbeing: national averages
(
    SELECT MAX(calendar_year) AS latest_year,
           AVG(CASE WHEN measure = 'Life satisfaction' AND estimate = 'Average (mean)' THEN value END) AS life_satisfaction,
           AVG(CASE WHEN measure = 'Happiness' AND estimate = 'Average (mean)' THEN value END) AS happiness,
           AVG(CASE WHEN measure = 'Anxiety' AND estimate = 'Average (mean)' THEN value END) AS anxiety
    FROM rs_fact_wellbeing
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM rs_fact_wellbeing)
) wb
CROSS JOIN
-- House prices: the latest complete year and the same D/S/T/F property types as mv_area_overview, which keeps the national figure comparable with the area ones
(
    SELECT MAX(calendar_year) AS latest_year,
           SUM(total_value)::FLOAT / NULLIF(SUM(transaction_count), 0) AS median_house_price,
           SUM(transaction_count) AS total_transactions
    FROM rs_fact_house_prices
    WHERE calendar_year = (
        SELECT MAX(calendar_year) FROM rs_fact_house_prices
        WHERE calendar_year < (SELECT MAX(calendar_year) FROM rs_fact_house_prices)
    )
      AND geography_code IS NOT NULL
      AND property_type IN ('D', 'S', 'T', 'F')
) hp
CROSS JOIN
-- Deprivation: national averages
(
    SELECT AVG(avg_imd_score) AS avg_imd_score,
           AVG(pct_most_deprived) AS pct_most_deprived
    FROM rs_fact_deprivation
) dep
CROSS JOIN
-- Universal Credit: latest period total (period_yyyymm sorts chronologically)
(
    SELECT TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') AS latest_period,
           SUM(claimant_count) AS total_uc_claimants
    FROM rs_fact_universal_credit
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM rs_fact_universal_credit)
) uc
CROSS JOIN
-- Children in low income families: latest year total (relative low income BHC)
-- rs_fact_children_low_income holds LA-level rows only; SUM does not double-count
(
    SELECT MAX(date_name) AS latest_period,
           SUM(children_count) AS total_children_low_income
    FROM rs_fact_children_low_income
    WHERE measure = 'relative_bhc'
      AND date_name = (SELECT MAX(date_name) FROM rs_fact_children_low_income WHERE measure = 'relative_bhc')
) cilif
CROSS JOIN
-- PIP: latest month total (LA-level rows only, no double-counting)
(
    SELECT TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') AS latest_period,
           SUM(caseload_count) AS total_pip_claimants
    FROM rs_fact_pip
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM rs_fact_pip)
) pip
CROSS JOIN
-- Claimant count: latest month total, the same grain as mv_area_overview
(
    SELECT TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') AS latest_year,
           SUM(claimant_count) AS total_claimant_count
    FROM rs_fact_claimant_count
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM rs_fact_claimant_count)
) cc
CROSS JOIN
-- Employment: average of the council rates for the latest rolling year
(
    SELECT AVG(CASE WHEN TRIM(variable_name) = 'Employment rate - aged 16-64' THEN obs_value END) AS employment_rate,
           AVG(CASE WHEN TRIM(variable_name) = 'Unemployment rate - aged 16-64' THEN obs_value END) AS unemployment_rate
    FROM rs_fact_employment
    WHERE measures_name = 'Variable'
      AND period_end_yyyymm = (SELECT MAX(period_end_yyyymm) FROM rs_fact_employment WHERE measures_name = 'Variable')
) emp
CROSS JOIN
-- Crime: rolling 12 complete months (exclude latest incomplete month)
(
    SELECT MAX(month) AS latest_year,
           SUM(crime_count) AS total_crimes
    FROM rs_fact_crime
    WHERE geography_code IS NOT NULL
      AND month >= (
        SELECT TO_CHAR(DATEADD(month, -12, TO_DATE(MAX(month) || '-01', 'YYYY-MM-DD')), 'YYYY-MM')
        FROM rs_fact_crime
        WHERE month < (SELECT MAX(month) FROM rs_fact_crime)
      )
      AND month < (SELECT MAX(month) FROM rs_fact_crime)
) cr
CROSS JOIN
-- Schools: England's headline Attainment 8
(
    SELECT MAX(calendar_year) AS latest_year,
           MAX(avg_att8) AS avg_attainment_8
    FROM rs_fact_school_performance
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM rs_fact_school_performance)
      AND geography_code = 'E92000001' AND breakdown_topic = 'Total'
) sch

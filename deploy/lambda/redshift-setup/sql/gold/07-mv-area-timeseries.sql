-- Key metrics by local authority and year, joined from the rs_* objects
DROP MATERIALIZED VIEW IF EXISTS mv_area_timeseries;

CREATE MATERIALIZED VIEW mv_area_timeseries AS
SELECT
    g.geography_code,
    g.geography_name,
    t.calendar_year,
    pop.total_population,
    earn.median_weekly_pay,
    wb.life_satisfaction,
    hp.median_house_price,
    cc.claimant_count,
    uc.uc_claimants,
    hb.hb_claimants,
    cilif.children_low_income,
    pip.pip_claimants,
    emp.employment_rate,
    emp.unemployment_rate,
    cr.total_crimes,
    rt.all_motor_vehicles,
    aps.econ_activity_rate,
    aps.pct_nvq4_plus,
    gva.total_gva,
    aq.pm25_total,
    spend.total_service_spend_k,
    jd.total_jobs,
    bc.active_enterprises,
    bd.live_births,
    bd.deaths
FROM public.rs_dim_geography g
-- rs_dim_time is month-grain. DISTINCT keeps this view at annual grain
CROSS JOIN (SELECT DISTINCT calendar_year FROM public.rs_dim_time) t
LEFT JOIN (
    SELECT geography_code, calendar_year, SUM(population) as total_population
    FROM public.rs_fact_population WHERE sex = 'All' AND age = 'Total'
    GROUP BY geography_code, calendar_year
) pop ON g.geography_code = pop.geography_code AND t.calendar_year = pop.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, AVG(value) as median_weekly_pay
    FROM public.rs_fact_earnings
    WHERE percentile = 'Median' AND sex = 'All' AND working_pattern = 'All'
      AND measure = 'Weekly pay - Gross' AND workplace_residence = 'Workplace'
    GROUP BY geography_code, calendar_year
) earn ON g.geography_code = earn.geography_code AND t.calendar_year = earn.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year,
        MAX(CASE WHEN measure = 'Life satisfaction' AND estimate = 'Average (mean)' THEN value END) as life_satisfaction
    FROM public.rs_fact_wellbeing
    GROUP BY geography_code, calendar_year
) wb ON g.geography_code = wb.geography_code AND t.calendar_year = wb.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, SUM(total_value)::FLOAT / NULLIF(SUM(transaction_count), 0) as median_house_price
    FROM public.rs_fact_house_prices
    WHERE geography_code IS NOT NULL
      AND property_type IN ('D', 'S', 'T', 'F')
    GROUP BY geography_code, calendar_year
) hp ON g.geography_code = hp.geography_code AND t.calendar_year = hp.calendar_year
LEFT JOIN (
    -- Claimant count is a monthly stock measure; the yearly figure is the latest month in each year
    SELECT geography_code, calendar_year, SUM(claimant_count) as claimant_count
    FROM public.rs_fact_claimant_count
    WHERE period_yyyymm IN (SELECT MAX(period_yyyymm) FROM public.rs_fact_claimant_count GROUP BY calendar_year)
    GROUP BY geography_code, calendar_year
) cc ON g.geography_code = cc.geography_code AND t.calendar_year = cc.calendar_year
LEFT JOIN (
    -- UC is a monthly stock measure; the yearly figure is the latest month in each year
    SELECT geography_code, calendar_year, SUM(claimant_count) as uc_claimants
    FROM public.rs_fact_universal_credit
    WHERE period_yyyymm IN (SELECT MAX(period_yyyymm) FROM public.rs_fact_universal_credit GROUP BY calendar_year)
    GROUP BY geography_code, calendar_year
) uc ON g.geography_code = uc.geography_code AND t.calendar_year = uc.calendar_year
LEFT JOIN (
    -- HB is a monthly stock measure: the latest month per year, not a yearly sum
    SELECT geography_code, calendar_year, SUM(caseload_count) as hb_claimants
    FROM public.rs_fact_housing_benefit
    WHERE date_name IN (SELECT MAX(date_name) FROM public.rs_fact_housing_benefit GROUP BY calendar_year)
    GROUP BY geography_code, calendar_year
) hb ON g.geography_code = hb.geography_code AND t.calendar_year = hb.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, SUM(children_count) as children_low_income
    FROM public.rs_fact_children_low_income
    WHERE measure = 'relative_bhc'
    GROUP BY geography_code, calendar_year
) cilif ON g.geography_code = cilif.geography_code AND t.calendar_year = cilif.calendar_year
LEFT JOIN (
    -- PIP is a monthly stock measure: the latest month per year, not a yearly sum
    SELECT geography_code, calendar_year, SUM(caseload_count) as pip_claimants
    FROM public.rs_fact_pip
    WHERE date_name IN (SELECT MAX(date_name) FROM public.rs_fact_pip GROUP BY calendar_year)
    GROUP BY geography_code, calendar_year
) pip ON g.geography_code = pip.geography_code AND t.calendar_year = pip.calendar_year
LEFT JOIN (
    SELECT geography_code,
           CAST(SUBSTRING(date_name, 5, 4) AS INT) as calendar_year,
           AVG(CASE WHEN TRIM(variable_name) = 'Employment rate - aged 16-64' THEN obs_value END) as employment_rate,
           AVG(CASE WHEN TRIM(variable_name) = 'Unemployment rate - aged 16-64' THEN obs_value END) as unemployment_rate
    FROM public.rs_fact_employment
    WHERE measures_name = 'Variable' AND date_name LIKE 'Jan %'
    GROUP BY geography_code, CAST(SUBSTRING(date_name, 5, 4) AS INT)
) emp ON g.geography_code = emp.geography_code AND t.calendar_year = emp.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, SUM(crime_count) as total_crimes
    FROM public.rs_fact_crime WHERE geography_code IS NOT NULL
    GROUP BY geography_code, calendar_year
) cr ON g.geography_code = cr.geography_code AND t.calendar_year = cr.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, all_motor_vehicles
    FROM public.rs_fact_road_traffic
) rt ON g.geography_code = rt.geography_code AND t.calendar_year = rt.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year,
        MAX(CASE WHEN variable_name = 'Economic activity rate - aged 16-64' THEN obs_value END) as econ_activity_rate,
        MAX(CASE WHEN variable_name ILIKE '%NVQ4+%aged 16-64' THEN obs_value END) as pct_nvq4_plus
    FROM public.rs_fact_aps
    GROUP BY geography_code, calendar_year
) aps ON g.geography_code = aps.geography_code AND t.calendar_year = aps.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, MAX(gva_value) as total_gva
    FROM public.rs_fact_gva
    WHERE price_type = 'Current prices'
      AND sic_code = 'total'
    GROUP BY geography_code, calendar_year
) gva ON g.geography_code = gva.geography_code AND t.calendar_year = gva.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, pm25_total
    FROM public.rs_fact_air_quality
) aq ON g.geography_code = aq.geography_code AND t.calendar_year = aq.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, total_service_net_exp as total_service_spend_k
    FROM public.rs_fact_la_spending
) spend ON g.geography_code = spend.geography_code AND t.calendar_year = spend.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, total_jobs
    FROM public.rs_fact_jobs_density
) jd ON g.geography_code = jd.geography_code AND t.calendar_year = jd.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, active_enterprises
    FROM public.rs_fact_business_counts
) bc ON g.geography_code = bc.geography_code AND t.calendar_year = bc.calendar_year
LEFT JOIN (
    SELECT geography_code, calendar_year, live_births, deaths
    FROM public.rs_fact_births_deaths
) bd ON g.geography_code = bd.geography_code AND t.calendar_year = bd.calendar_year
WHERE g.geography_type = 'local_authority'
  AND (pop.total_population IS NOT NULL
   OR earn.median_weekly_pay IS NOT NULL
   OR wb.life_satisfaction IS NOT NULL
   OR hp.median_house_price IS NOT NULL
   OR cc.claimant_count IS NOT NULL
   OR uc.uc_claimants IS NOT NULL
   OR hb.hb_claimants IS NOT NULL
   OR cilif.children_low_income IS NOT NULL
   OR pip.pip_claimants IS NOT NULL
   OR emp.employment_rate IS NOT NULL
   OR emp.unemployment_rate IS NOT NULL
   OR cr.total_crimes IS NOT NULL
   OR rt.all_motor_vehicles IS NOT NULL
   OR aps.econ_activity_rate IS NOT NULL
   OR aps.pct_nvq4_plus IS NOT NULL
   OR gva.total_gva IS NOT NULL
   OR aq.pm25_total IS NOT NULL
   OR spend.total_service_spend_k IS NOT NULL
   OR jd.total_jobs IS NOT NULL
   OR bc.active_enterprises IS NOT NULL
   OR bd.live_births IS NOT NULL
   OR bd.deaths IS NOT NULL)

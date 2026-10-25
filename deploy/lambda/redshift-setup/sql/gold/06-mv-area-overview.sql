-- One row per local authority with the latest value of every metric, joined from the rs_* objects
DROP MATERIALIZED VIEW IF EXISTS mv_area_overview;

CREATE MATERIALIZED VIEW mv_area_overview AS
SELECT
    g.geography_code,
    g.geography_name,
    g.latitude,
    g.longitude,
    pop.total_population,
    pop.year AS population_year,
    earn.median_weekly_pay,
    earn.year AS earnings_year,
    wb.life_satisfaction,
    wb.happiness,
    wb.anxiety,
    wb.year AS wellbeing_year,
    sch.avg_attainment_8,
    sch.year AS school_performance_year,
    hp.median_house_price,
    hp.total_transactions,
    hp.year AS house_prices_year,
    dep.avg_imd_score,
    dep.pct_most_deprived,
    dep.year AS deprivation_year,
    uc.latest_uc_claimants,
    uc.period AS uc_period,
    hb.latest_hb_claimants,
    hb.period AS hb_period,
    cilif.latest_children_low_income,
    cilif.period AS children_low_income_period,
    pip.latest_pip_claimants,
    pip.period AS pip_period,
    cc.latest_claimant_count,
    cc.year AS claimant_count_year,
    emp.employment_rate,
    emp.unemployment_rate,
    emp.period AS employment_period,
    cr.total_crimes,
    cr.crime_rate_per_1000,
    cr.period AS crime_period,
    rt.all_motor_vehicles,
    rt.year AS road_traffic_year,
    aps.econ_activity_rate,
    aps.pct_nvq4_plus,
    aps.pct_no_qualifications,
    aps.year AS aps_year,
    gva.total_gva,
    gva.year AS gva_year,
    ods.gp_practice_count,
    ods.pharmacy_count,
    ods.snapshot_date AS nhs_ods_snapshot_date,
    aq.pm25_total,
    aq.pm25_anthropogenic,
    aq.year AS air_quality_year,
    spend.total_service_spend_k,
    spend.adult_social_care_spend_k,
    spend.year AS la_spending_year,
    jd.total_jobs,
    jd.jobs_density,
    jd.year AS jobs_density_year,
    bc.active_enterprises,
    bc.year AS business_counts_year,
    bd.live_births,
    bd.deaths,
    bd.year AS births_deaths_year
FROM public.rs_dim_geography g
LEFT JOIN (
    SELECT geography_code, SUM(population) as total_population,
        MAX(calendar_year) as year
    FROM public.rs_fact_population
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_population)
      AND sex = 'All'
      AND age = 'Total'
    GROUP BY geography_code
) pop ON g.geography_code = pop.geography_code
LEFT JOIN (
    SELECT geography_code, AVG(value) as median_weekly_pay,
        MAX(calendar_year) as year
    FROM public.rs_fact_earnings
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_earnings)
      AND percentile = 'Median' AND sex = 'All' AND working_pattern = 'All'
      AND measure = 'Weekly pay - Gross' AND workplace_residence = 'Workplace'
    GROUP BY geography_code
) earn ON g.geography_code = earn.geography_code
LEFT JOIN (
    SELECT geography_code,
        MAX(CASE WHEN measure = 'Life satisfaction' AND estimate = 'Average (mean)' THEN value END) as life_satisfaction,
        MAX(CASE WHEN measure = 'Happiness' AND estimate = 'Average (mean)' THEN value END) as happiness,
        MAX(CASE WHEN measure = 'Anxiety' AND estimate = 'Average (mean)' THEN value END) as anxiety,
        MAX(calendar_year) as year
    FROM public.rs_fact_wellbeing
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_wellbeing)
    GROUP BY geography_code
) wb ON g.geography_code = wb.geography_code
LEFT JOIN (
    SELECT geography_code, MAX(avg_att8) as avg_attainment_8,
        MAX(calendar_year) as year
    FROM public.rs_fact_school_performance
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_school_performance)
      AND breakdown_topic = 'Total'
    GROUP BY geography_code
) sch ON g.geography_code = sch.geography_code
LEFT JOIN (
    SELECT geography_code,
        SUM(total_value)::FLOAT / NULLIF(SUM(transaction_count), 0) as median_house_price,
        SUM(transaction_count) as total_transactions,
        MAX(calendar_year) as year
    FROM public.rs_fact_house_prices
    WHERE calendar_year = (
        SELECT MAX(calendar_year) FROM public.rs_fact_house_prices
        WHERE calendar_year < (SELECT MAX(calendar_year) FROM public.rs_fact_house_prices)
    )
      AND geography_code IS NOT NULL
      AND property_type IN ('D', 'S', 'T', 'F')
    GROUP BY geography_code
) hp ON g.geography_code = hp.geography_code
LEFT JOIN (
    SELECT geography_code, avg_imd_score, pct_most_deprived,
        2025 as year
    FROM public.rs_fact_deprivation
) dep ON g.geography_code = dep.geography_code
LEFT JOIN (
    SELECT geography_code, SUM(claimant_count) as latest_uc_claimants,
        TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') as period
    FROM public.rs_fact_universal_credit
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM public.rs_fact_universal_credit)
    GROUP BY geography_code
) uc ON g.geography_code = uc.geography_code
LEFT JOIN (
    SELECT geography_code, SUM(caseload_count) as latest_hb_claimants,
        TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') as period
    FROM public.rs_fact_housing_benefit
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM public.rs_fact_housing_benefit)
    GROUP BY geography_code
) hb ON g.geography_code = hb.geography_code
LEFT JOIN (
    SELECT geography_code, SUM(children_count) as latest_children_low_income,
        MAX(date_name) as period
    FROM public.rs_fact_children_low_income
    WHERE measure = 'relative_bhc'
      AND date_name = (SELECT MAX(date_name) FROM public.rs_fact_children_low_income WHERE measure = 'relative_bhc')
    GROUP BY geography_code
) cilif ON g.geography_code = cilif.geography_code
LEFT JOIN (
    SELECT geography_code, SUM(caseload_count) as latest_pip_claimants,
        TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') as period
    FROM public.rs_fact_pip
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM public.rs_fact_pip)
    GROUP BY geography_code
) pip ON g.geography_code = pip.geography_code
LEFT JOIN (
    SELECT geography_code, SUM(claimant_count) as latest_claimant_count,
        TO_CHAR(TO_DATE(MAX(period_yyyymm)::VARCHAR, 'YYYYMM'), 'FMMonth YYYY') as year
    FROM public.rs_fact_claimant_count
    WHERE period_yyyymm = (SELECT MAX(period_yyyymm) FROM public.rs_fact_claimant_count)
    GROUP BY geography_code
) cc ON g.geography_code = cc.geography_code
LEFT JOIN (
    SELECT geography_code,
        AVG(CASE WHEN TRIM(variable_name) = 'Employment rate - aged 16-64' THEN obs_value END) as employment_rate,
        AVG(CASE WHEN TRIM(variable_name) = 'Unemployment rate - aged 16-64' THEN obs_value END) as unemployment_rate,
        MAX(date_name) as period
    FROM public.rs_fact_employment
    WHERE measures_name = 'Variable'
      AND period_end_yyyymm = (SELECT MAX(period_end_yyyymm) FROM public.rs_fact_employment WHERE measures_name = 'Variable')
    GROUP BY geography_code
) emp ON g.geography_code = emp.geography_code
LEFT JOIN (
    SELECT c.geography_code,
        SUM(crime_count) as total_crimes,
        ROUND(SUM(crime_count)::FLOAT / NULLIF(MAX(p.total_population), 0) * 1000, 1) as crime_rate_per_1000,
        TO_CHAR(TO_DATE(MIN(c.month) || '-01', 'YYYY-MM-DD'), 'FMMonth YYYY')
            || ' to '
            || TO_CHAR(TO_DATE(MAX(c.month) || '-01', 'YYYY-MM-DD'), 'FMMonth YYYY') as period
    FROM public.rs_fact_crime c
    LEFT JOIN (
        SELECT geography_code, SUM(population) as total_population
        FROM public.rs_fact_population WHERE sex = 'All' AND age = 'Total'
          AND calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_population)
        GROUP BY geography_code
    ) p ON c.geography_code = p.geography_code
    WHERE c.geography_code IS NOT NULL
      AND c.month >= (
        SELECT TO_CHAR(DATEADD(month, -12, TO_DATE(MAX(month) || '-01', 'YYYY-MM-DD')), 'YYYY-MM')
        FROM public.rs_fact_crime
        WHERE month < (SELECT MAX(month) FROM public.rs_fact_crime)
      )
      AND c.month < (SELECT MAX(month) FROM public.rs_fact_crime)
    GROUP BY c.geography_code
) cr ON g.geography_code = cr.geography_code
LEFT JOIN (
    SELECT geography_code, all_motor_vehicles,
        calendar_year as year
    FROM public.rs_fact_road_traffic
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_road_traffic)
) rt ON g.geography_code = rt.geography_code
LEFT JOIN (
    SELECT geography_code,
        MAX(CASE WHEN variable_name = 'Economic activity rate - aged 16-64' THEN obs_value END) as econ_activity_rate,
        MAX(CASE WHEN variable_name ILIKE '%NVQ4+%aged 16-64' THEN obs_value END) as pct_nvq4_plus,
        MAX(CASE WHEN variable_name ILIKE '%no qualifications%aged 16-64' THEN obs_value END) as pct_no_qualifications,
        MAX(calendar_year) as year
    FROM public.rs_fact_aps
    WHERE calendar_year = (
        SELECT MAX(calendar_year) FROM public.rs_fact_aps
        WHERE variable_name ILIKE '%NVQ4+%aged 16-64'
    )
    GROUP BY geography_code
) aps ON g.geography_code = aps.geography_code
LEFT JOIN (
    SELECT geography_code, gva_value as total_gva,
        calendar_year as year
    FROM public.rs_fact_gva
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_gva)
      AND price_type = 'Current prices'
      AND sic_code = 'total'
) gva ON g.geography_code = gva.geography_code
LEFT JOIN (
    SELECT geography_code,
        COUNT(CASE WHEN org_type = 'gp-practices' THEN 1 END) as gp_practice_count,
        COUNT(CASE WHEN org_type = 'pharmacies' THEN 1 END) as pharmacy_count,
        MAX(snapshot_date) as snapshot_date
    FROM public.rs_fact_nhs_ods
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM public.rs_fact_nhs_ods)
      AND status = 'Active'
    GROUP BY geography_code
) ods ON g.geography_code = ods.geography_code
LEFT JOIN (
    SELECT geography_code, pm25_total, pm25_anthropogenic,
        calendar_year as year
    FROM public.rs_fact_air_quality
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_air_quality)
) aq ON g.geography_code = aq.geography_code
LEFT JOIN (
    SELECT geography_code,
        total_service_net_exp as total_service_spend_k,
        adult_social_care_net_exp as adult_social_care_spend_k,
        calendar_year as year
    FROM public.rs_fact_la_spending
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_la_spending)
) spend ON g.geography_code = spend.geography_code
LEFT JOIN (
    SELECT geography_code, total_jobs, jobs_density,
        calendar_year as year
    FROM public.rs_fact_jobs_density
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_jobs_density)
) jd ON g.geography_code = jd.geography_code
LEFT JOIN (
    SELECT geography_code, active_enterprises,
        calendar_year as year
    FROM public.rs_fact_business_counts
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_business_counts)
) bc ON g.geography_code = bc.geography_code
LEFT JOIN (
    SELECT geography_code, live_births, deaths,
        calendar_year as year
    FROM public.rs_fact_births_deaths
    WHERE calendar_year = (SELECT MAX(calendar_year) FROM public.rs_fact_births_deaths)
) bd ON g.geography_code = bd.geography_code
WHERE g.geography_type = 'local_authority'

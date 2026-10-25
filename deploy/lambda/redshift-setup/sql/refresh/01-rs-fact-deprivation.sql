CREATE MATERIALIZED VIEW rs_fact_deprivation AS
SELECT
    geography_code::VARCHAR(20),
    la_code::VARCHAR(20),
    la_name::VARCHAR(200),
    avg_imd_score::FLOAT,
    avg_imd_rank::FLOAT,
    lsoa_count::BIGINT,
    lsoas_in_most_deprived_decile::BIGINT,
    pct_most_deprived::FLOAT,
    avg_income_score::FLOAT,
    avg_employment_score::FLOAT,
    avg_education_score::FLOAT,
    avg_health_score::FLOAT,
    avg_crime_score::FLOAT,
    avg_housing_score::FLOAT,
    avg_living_env_score::FLOAT,
    total_population::BIGINT
FROM gold.fact_deprivation;

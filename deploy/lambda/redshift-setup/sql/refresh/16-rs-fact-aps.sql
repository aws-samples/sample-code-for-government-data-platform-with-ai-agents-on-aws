CREATE MATERIALIZED VIEW rs_fact_aps AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    date_name::VARCHAR(50),
    calendar_year::INT,
    variable_name::VARCHAR(200),
    measures_name::VARCHAR(50),
    obs_value::FLOAT
FROM gold.fact_aps;

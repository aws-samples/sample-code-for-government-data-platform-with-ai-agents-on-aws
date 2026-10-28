CREATE TABLE rs_fact_employment AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    date_name::VARCHAR(100),
    variable_name::VARCHAR(200),
    measures_name::VARCHAR(100),
    obs_value::FLOAT,
    period_end_yyyymm::INT
FROM gold.fact_employment;

CREATE MATERIALIZED VIEW rs_fact_children_low_income AS
SELECT
    geography_code::VARCHAR(20),
    la_name::VARCHAR(200),
    date_name::VARCHAR(50),
    calendar_year::INT,
    measure::VARCHAR(20),
    children_count::BIGINT
FROM gold.fact_children_low_income;

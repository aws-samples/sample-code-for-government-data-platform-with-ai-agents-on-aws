CREATE MATERIALIZED VIEW rs_fact_wellbeing AS
SELECT
    geography_code::VARCHAR(20),
    measure::VARCHAR(100),
    estimate::VARCHAR(100),
    calendar_year::INT,
    period::VARCHAR(20),
    value::FLOAT,
    lower_limit::FLOAT,
    upper_limit::FLOAT
FROM gold.fact_wellbeing;

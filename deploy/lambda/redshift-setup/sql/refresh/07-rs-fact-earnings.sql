CREATE MATERIALIZED VIEW rs_fact_earnings AS
SELECT
    geography_code::VARCHAR(20),
    sex::VARCHAR(20),
    working_pattern::VARCHAR(50),
    measure::VARCHAR(200),
    percentile::VARCHAR(50),
    workplace_residence::VARCHAR(50),
    calendar_year::INT,
    value::FLOAT,
    coefficient_of_variation::FLOAT
FROM gold.fact_earnings;

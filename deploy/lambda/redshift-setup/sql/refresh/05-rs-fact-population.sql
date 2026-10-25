CREATE MATERIALIZED VIEW rs_fact_population AS
SELECT
    geography_code::VARCHAR(20),
    sex::VARCHAR(20),
    age::VARCHAR(50),
    calendar_year::INT,
    population::BIGINT
FROM gold.fact_population;

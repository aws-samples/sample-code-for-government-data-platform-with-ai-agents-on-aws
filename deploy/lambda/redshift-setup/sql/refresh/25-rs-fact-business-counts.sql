
CREATE MATERIALIZED VIEW rs_fact_business_counts AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    active_enterprises::INT
FROM gold.fact_business_counts;

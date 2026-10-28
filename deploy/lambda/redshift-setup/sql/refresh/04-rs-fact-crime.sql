CREATE TABLE rs_fact_crime AS
SELECT
    category::VARCHAR(100),
    month::VARCHAR(10),
    street_name::VARCHAR(200),
    outcome_category::VARCHAR(200),
    crime_count::BIGINT,
    avg_latitude::FLOAT,
    avg_longitude::FLOAT,
    calendar_year::INT,
    period_yyyymm::INT,
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200)
FROM gold.fact_crime;


CREATE TABLE rs_fact_air_quality AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    pm25_total::FLOAT,
    pm25_non_anthropogenic::FLOAT,
    pm25_anthropogenic::FLOAT
FROM gold.fact_air_quality;

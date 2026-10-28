
CREATE TABLE rs_fact_births_deaths AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    live_births::INT,
    deaths::INT
FROM gold.fact_births_deaths;

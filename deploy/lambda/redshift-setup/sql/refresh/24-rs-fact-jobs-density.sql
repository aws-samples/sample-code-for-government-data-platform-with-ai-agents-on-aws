
CREATE TABLE rs_fact_jobs_density AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    total_jobs::FLOAT,
    jobs_density::FLOAT
FROM gold.fact_jobs_density;

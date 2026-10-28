CREATE TABLE rs_fact_claimant_count AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    date_name::VARCHAR(50),
    period_yyyymm::INT,
    calendar_year::INT,
    claimant_count::BIGINT
FROM gold.fact_claimant_count;

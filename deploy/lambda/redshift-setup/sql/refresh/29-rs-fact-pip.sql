CREATE MATERIALIZED VIEW rs_fact_pip AS
SELECT
    geography_code::VARCHAR(20),
    la_name::VARCHAR(200),
    date_name::VARCHAR(50),
    period_yyyymm::INT,
    calendar_year::INT,
    caseload_count::BIGINT
FROM gold.fact_pip;

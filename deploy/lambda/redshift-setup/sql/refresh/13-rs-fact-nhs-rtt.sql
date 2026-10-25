CREATE MATERIALIZED VIEW rs_fact_nhs_rtt AS
SELECT
    calendar_year::INT,
    month_name::VARCHAR(20),
    period_yyyymm::INT,
    commissioner_org_code::VARCHAR(10),
    commissioner_org_name::VARCHAR(200),
    commissioner_parent_org_code::VARCHAR(10),
    commissioner_parent_name::VARCHAR(200),
    total_waiting::BIGINT,
    waiting_over_18_weeks::BIGINT,
    waiting_over_52_weeks::BIGINT,
    pct_over_18_weeks::FLOAT
FROM gold.nhs_rtt_waiting_times;

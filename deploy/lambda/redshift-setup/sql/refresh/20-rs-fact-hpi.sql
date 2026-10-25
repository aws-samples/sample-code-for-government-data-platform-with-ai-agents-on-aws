
CREATE TABLE rs_fact_hpi AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    date::DATE,
    calendar_year::INT,
    calendar_month::INT,
    period_yyyymm::INT,
    average_price::FLOAT,
    monthly_change_pct::FLOAT,
    annual_change_pct::FLOAT,
    average_price_sa::FLOAT
FROM gold.fact_hpi;

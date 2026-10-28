CREATE TABLE rs_dim_time AS
SELECT
    period_yyyymm::INT,
    calendar_year::INT,
    calendar_month::INT,
    month_name::VARCHAR(20),
    quarter::INT,
    fiscal_year::INT,
    decade::INT,
    display_label::VARCHAR(30)
FROM gold.dim_time;

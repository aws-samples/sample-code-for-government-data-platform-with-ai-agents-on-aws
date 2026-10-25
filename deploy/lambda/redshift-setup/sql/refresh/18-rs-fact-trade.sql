CREATE MATERIALIZED VIEW rs_fact_trade AS
SELECT
    month_id::INT,
    period_yyyymm::INT,
    calendar_year::INT,
    month::INT,
    region_name::VARCHAR(100),
    region_group::VARCHAR(100),
    region_id::INT,
    country_name::VARCHAR(200),
    country_code::VARCHAR(10),
    flow_type::VARCHAR(50),
    sitc2_id::INT,
    trade_value::FLOAT,
    net_mass_kg::FLOAT
FROM gold.fact_trade;

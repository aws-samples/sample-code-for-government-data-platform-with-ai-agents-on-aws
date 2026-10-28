CREATE TABLE rs_fact_gva AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    sic_code::VARCHAR(20),
    industry::VARCHAR(200),
    price_type::VARCHAR(100),
    gva_value::FLOAT
FROM gold.fact_gva;

CREATE TABLE rs_fact_house_prices AS
SELECT
    geography_code::VARCHAR(20),
    district::VARCHAR(200),
    county::VARCHAR(200),
    property_type::VARCHAR(50),
    old_new::VARCHAR(10),
    duration::VARCHAR(20),
    transaction_count::BIGINT,
    min_price::BIGINT,
    max_price::BIGINT,
    avg_price::FLOAT,
    median_price::BIGINT,
    total_value::BIGINT,
    calendar_year::INT
FROM gold.fact_house_prices;

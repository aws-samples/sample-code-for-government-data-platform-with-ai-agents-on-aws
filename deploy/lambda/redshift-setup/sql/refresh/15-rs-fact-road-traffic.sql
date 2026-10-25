CREATE MATERIALIZED VIEW rs_fact_road_traffic AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    calendar_year::INT,
    total_link_length_km::FLOAT,
    total_link_length_miles::FLOAT,
    cars_and_taxis::BIGINT,
    all_motor_vehicles::BIGINT
FROM gold.fact_road_traffic;

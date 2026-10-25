CREATE MATERIALIZED VIEW rs_dim_geography AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    latitude::FLOAT,
    longitude::FLOAT,
    geography_type::VARCHAR(30)
FROM gold.dim_geography;

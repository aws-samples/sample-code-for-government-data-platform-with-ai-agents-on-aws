CREATE TABLE rs_dim_region_mapping AS
SELECT
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    region_code::VARCHAR(20),
    region_name::VARCHAR(100)
FROM gold.dim_region_mapping;

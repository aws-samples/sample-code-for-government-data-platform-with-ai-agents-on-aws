
CREATE TABLE rs_fact_nhs_ods AS
SELECT
    org_id::VARCHAR(20),
    org_name::VARCHAR(300),
    status::VARCHAR(20),
    primary_role_id::VARCHAR(10),
    primary_role_description::VARCHAR(200),
    org_type::VARCHAR(50),
    postcode::VARCHAR(10),
    last_change_date::VARCHAR(10),
    geography_code::VARCHAR(20),
    geography_name::VARCHAR(200),
    snapshot_date::VARCHAR(10)
FROM gold.fact_nhs_ods;

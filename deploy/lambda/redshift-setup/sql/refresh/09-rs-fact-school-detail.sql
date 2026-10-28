CREATE TABLE rs_fact_school_detail AS
SELECT
    school_urn::VARCHAR(20),
    school_name::VARCHAR(300),
    school_laestab::VARCHAR(20),
    geography_code::VARCHAR(20),
    la_name::VARCHAR(200),
    calendar_year::INT,
    time_period::VARCHAR(20),
    time_identifier::VARCHAR(50),
    version::VARCHAR(20),
    establishment_type_group::VARCHAR(100),
    breakdown_topic::VARCHAR(100),
    breakdown::VARCHAR(100),
    sex::VARCHAR(20),
    disadvantage_status::VARCHAR(50),
    TRY_CAST(pupil_count AS FLOAT) AS pupil_count,
    TRY_CAST(attainment8_average AS FLOAT) AS attainment8_average,
    TRY_CAST(progress8_average AS FLOAT) AS progress8_average,
    TRY_CAST(progress8_lower_ci AS FLOAT) AS progress8_lower_ci,
    TRY_CAST(progress8_upper_ci AS FLOAT) AS progress8_upper_ci,
    TRY_CAST(engmath_94_percent AS FLOAT) AS engmath_94_percent,
    TRY_CAST(engmath_95_percent AS FLOAT) AS engmath_95_percent
FROM gold.fact_school_detail;

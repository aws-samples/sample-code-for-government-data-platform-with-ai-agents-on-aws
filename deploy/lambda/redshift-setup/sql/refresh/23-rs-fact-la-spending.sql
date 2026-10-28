
CREATE TABLE rs_fact_la_spending AS
SELECT
    geography_code::VARCHAR(20),
    la_name::VARCHAR(200),
    la_class::VARCHAR(100),
    calendar_year::INT,
    financial_year_start::INT,
    education_net_exp::FLOAT,
    childrens_social_care_net_exp::FLOAT,
    adult_social_care_net_exp::FLOAT,
    public_health_net_exp::FLOAT,
    housing_net_exp::FLOAT,
    cultural_net_exp::FLOAT,
    environment_net_exp::FLOAT,
    planning_net_exp::FLOAT,
    transport_net_exp::FLOAT,
    police_net_exp::FLOAT,
    fire_rescue_net_exp::FLOAT,
    central_net_exp::FLOAT,
    other_net_exp::FLOAT,
    total_service_net_exp::FLOAT
FROM gold.fact_la_spending;

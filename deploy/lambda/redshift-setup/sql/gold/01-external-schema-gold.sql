-- Spectrum schema over the Glue resource link to the gold S3 Tables; refresh/00 recreates it, this only creates it on a fresh deployment
CREATE EXTERNAL SCHEMA IF NOT EXISTS gold
FROM DATA CATALOG
DATABASE '{gold_database}'
IAM_ROLE '{spectrum_role}'
REGION '{region}'
CATALOG_ID '{account_id}'

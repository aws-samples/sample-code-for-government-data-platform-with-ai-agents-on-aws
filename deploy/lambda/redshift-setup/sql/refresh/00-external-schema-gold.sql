-- Recreated on every refresh in case the Glue database it points at changed
DROP SCHEMA IF EXISTS gold;
CREATE EXTERNAL SCHEMA gold
FROM DATA CATALOG
DATABASE '{gold_database}'
IAM_ROLE '{spectrum_role}'
REGION '{region}'
CATALOG_ID '{account_id}'

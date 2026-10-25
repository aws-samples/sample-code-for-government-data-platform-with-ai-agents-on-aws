"""Bronze to silver for MHCLG Revenue Outturn: the RS_* net expenditure columns per local authority and financial year."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, substring
from pyspark.sql.types import IntegerType, DoubleType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/mhclg/spending/",
    header=True,
    inferSchema=False,
)

# Identifiers and the RS_* net expenditure columns in £ thousands; year_ending 201803 is FY 2017-18
spending_df = df.select(
    trim(col("year_ending")).alias("year_ending_raw"),
    trim(col("ONS_code")).alias("geography_code"),
    trim(col("LA_name")).alias("la_name"),
    trim(col("LA_class")).alias("la_class"),
    trim(col("status")).alias("status"),
    col("RS_edu_net_exp").cast(DoubleType()).alias("education_net_exp"),
    col("RS_csc_net_exp").cast(DoubleType()).alias("childrens_social_care_net_exp"),
    col("RS_asc_net_exp").cast(DoubleType()).alias("adult_social_care_net_exp"),
    col("RS_phs_net_exp").cast(DoubleType()).alias("public_health_net_exp"),
    col("RS_hous_net_exp").cast(DoubleType()).alias("housing_net_exp"),
    col("RS_cul_net_exp").cast(DoubleType()).alias("cultural_net_exp"),
    col("RS_env_net_exp").cast(DoubleType()).alias("environment_net_exp"),
    col("RS_plan_net_exp").cast(DoubleType()).alias("planning_net_exp"),
    col("RS_trans_net_exp").cast(DoubleType()).alias("transport_net_exp"),
    col("RS_pol_net_exp").cast(DoubleType()).alias("police_net_exp"),
    col("RS_frs_net_exp").cast(DoubleType()).alias("fire_rescue_net_exp"),
    col("RS_cen_net_exp").cast(DoubleType()).alias("central_net_exp"),
    col("RS_oth_net_exp").cast(DoubleType()).alias("other_net_exp"),
    col("RS_totsx_net_exp").cast(DoubleType()).alias("total_service_net_exp"),
).filter(
    # Only individual councils with ONS codes, not the aggregate rows
    col("geography_code").startswith("E")
    & (col("status") != "total")
)

# year_ending 201803 is financial year 2017, reported as calendar_year 2017
spending_df = spending_df.withColumn(
    "financial_year_start",
    (substring(col("year_ending_raw"), 1, 4).cast(IntegerType()) - 1)
).withColumn(
    "calendar_year",
    substring(col("year_ending_raw"), 1, 4).cast(IntegerType()) - 1
).drop("year_ending_raw")

table_name = f"glue_catalog.{database}.la_spending"

write_timeseries(spark, spending_df, table_name, "calendar_year")
job.commit()

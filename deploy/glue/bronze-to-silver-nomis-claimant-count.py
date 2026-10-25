"""Bronze to silver for the Claimant Count by local authority and month (NOMIS NM_162_1)."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, regexp_extract
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/nomis/claimant-count/",
    header=True,
    inferSchema=False,
)

# NOMIS columns: DATE_NAME, GEOGRAPHY_NAME, GEOGRAPHY_CODE, OBS_VALUE
claimant_df = df.select(
    trim(col("DATE_NAME")).alias("date_name"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    col("OBS_VALUE").cast("integer").alias("claimant_count"),
).filter(
    col("OBS_VALUE").isNotNull() & (col("OBS_VALUE") != "")
)

# date_name is "November 2025"; the year is its last four characters
claimant_df = claimant_df.withColumn(
    "calendar_year",
    regexp_extract(col("date_name"), r"(\d{4})", 1).cast(IntegerType())
)

table_name = f"glue_catalog.{database}.claimant_count"

write_timeseries(spark, claimant_df, table_name, "calendar_year")
job.commit()

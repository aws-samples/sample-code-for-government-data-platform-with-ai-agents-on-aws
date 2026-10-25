"""Bronze to silver for ONS APS employment rates by local authority and period (NOMIS NM_17_5)."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/nomis/employment/",
    header=True,
    inferSchema=False,
    quote='"',
)

# NOMIS marks suppressed values with ! and *, which are dropped
employment_df = df.select(
    trim(col("DATE_NAME")).alias("date_name"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    trim(col("VARIABLE_NAME")).alias("variable_name"),
    trim(col("MEASURES_NAME")).alias("measures_name"),
    trim(col("OBS_VALUE")).alias("obs_value_raw"),
).filter(
    col("obs_value_raw").isNotNull()
    & (col("obs_value_raw") != "")
    & (~col("obs_value_raw").isin("!", "*", "~", "#", "-"))
).withColumn("obs_value", col("obs_value_raw").cast("double")).drop("obs_value_raw").filter(
    col("obs_value").isNotNull()
)

table_name = f"glue_catalog.{database}.employment"

write_timeseries(spark, employment_df, table_name, "date_name")
job.commit()

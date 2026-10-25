"""Bronze to silver for the NOMIS Annual Population Survey variables by local authority and period."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, regexp_extract
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

bronze_path = f"s3://{bucket}/bronze/nomis/aps/"
df = spark.read.option("header", "true").csv(bronze_path)

# calendar_year is the end year of date_name, e.g. "Jan 2004-Dec 2004" gives 2004
aps_df = df.select(
    trim(col("DATE_NAME")).alias("date_name"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    trim(col("VARIABLE_NAME")).alias("variable_name"),
    trim(col("MEASURES_NAME")).alias("measures_name"),
    col("OBS_VALUE").cast("double").alias("obs_value"),
).withColumn(
    "calendar_year",
    regexp_extract(col("date_name"), r"(\d{4})$", 1).cast(IntegerType())
)

aps_df = aps_df.filter(col("obs_value").isNotNull())

table_name = f"glue_catalog.{database}.aps"

write_timeseries(spark, aps_df, table_name, "calendar_year")

job.commit()

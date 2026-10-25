"""Bronze to silver for ONS births and deaths by local authority and year, joined into one table."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

births = spark.read.csv(
    f"s3://{bucket}/bronze/ons/births-deaths/births-by-la.csv",
    header=True, inferSchema=False,
)
births = births.select(
    trim(col("DATE_NAME")).cast(IntegerType()).alias("calendar_year"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    col("OBS_VALUE").cast(IntegerType()).alias("live_births"),
).filter(col("calendar_year").isNotNull())

deaths = spark.read.csv(
    f"s3://{bucket}/bronze/ons/births-deaths/deaths-by-la.csv",
    header=True, inferSchema=False,
)
deaths = deaths.select(
    trim(col("DATE_NAME")).cast(IntegerType()).alias("calendar_year"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    col("OBS_VALUE").cast(IntegerType()).alias("deaths"),
).filter(col("calendar_year").isNotNull())

df = births.join(deaths, on=["calendar_year", "geography_name", "geography_code"], how="outer")

table_name = f"glue_catalog.{database}.births_deaths"

write_timeseries(spark, df, table_name, "calendar_year")
job.commit()

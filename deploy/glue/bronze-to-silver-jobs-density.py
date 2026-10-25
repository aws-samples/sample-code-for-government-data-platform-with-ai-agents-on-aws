"""Bronze to silver for NOMIS jobs density, pivoted to total_jobs and jobs_density columns by local authority and year."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim
from pyspark.sql.types import IntegerType, DoubleType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/nomis/jobs-density/jobs-density-by-la.csv",
    header=True, inferSchema=False,
)

df = df.select(
    trim(col("DATE_NAME")).alias("date_name"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    trim(col("ITEM_NAME")).alias("item_name"),
    col("OBS_VALUE").cast(DoubleType()).alias("obs_value"),
)

pivoted = df.groupBy("date_name", "geography_name", "geography_code").pivot(
    "item_name", ["Total jobs", "Jobs density"]
).agg({"obs_value": "first"})

pivoted = pivoted.withColumnRenamed("Total jobs", "total_jobs") \
    .withColumnRenamed("Jobs density", "jobs_density") \
    .withColumn("calendar_year", col("date_name").cast(IntegerType())) \
    .filter(col("calendar_year").isNotNull())

table_name = f"glue_catalog.{database}.jobs_density"

write_timeseries(spark, pivoted, table_name, "calendar_year")
job.commit()

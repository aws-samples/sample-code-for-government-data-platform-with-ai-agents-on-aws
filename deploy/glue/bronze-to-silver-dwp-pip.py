"""Bronze to silver for DWP Personal Independence Payment caseload by local authority and month."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, substring
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/dwp/pip/",
    header=True,
    inferSchema=False,
    quote='"',
)

# date_name is yyyymm, e.g. 201901; the first four characters are the calendar year
pip_df = df.select(
    trim(col("geography_code")).alias("geography_code"),
    trim(col("la_name")).alias("la_name"),
    trim(col("date_name")).alias("date_name"),
    col("caseload_count").cast(IntegerType()),
).filter(
    col("caseload_count").isNotNull()
).withColumn(
    "calendar_year", substring(col("date_name"), 1, 4).cast(IntegerType())
)

table_name = f"glue_catalog.{database}.pip"

write_timeseries(spark, pip_df, table_name, "calendar_year")
job.commit()

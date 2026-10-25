"""Bronze to silver for NOMIS UK Business Counts: enterprises by local authority and year."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/nomis/business-counts/business-counts-by-la.csv",
    header=True, inferSchema=False,
)

df = df.select(
    trim(col("DATE_NAME")).cast(IntegerType()).alias("calendar_year"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    col("OBS_VALUE").cast(IntegerType()).alias("active_enterprises"),
).filter(col("calendar_year").isNotNull())

table_name = f"glue_catalog.{database}.business_counts"

write_timeseries(spark, df, table_name, "calendar_year")
job.commit()

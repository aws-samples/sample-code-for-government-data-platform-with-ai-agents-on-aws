"""Bronze to silver for DWP Universal Credit people on UC by local authority and month."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, regexp_extract
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/dwp/universal-credit/",
    header=True,
    inferSchema=False,
    quote='"',
)

uc_df = df.select(
    trim(col("geography_code")).alias("geography_code"),
    trim(col("la_name")).alias("la_name"),
    trim(col("date_name")).alias("date_name"),
    col("claimant_count").cast(IntegerType()),
).filter(
    col("claimant_count").isNotNull()
).withColumn(
    "calendar_year", regexp_extract(col("date_name"), r"(\d{4})", 1).cast(IntegerType())
)

table_name = f"glue_catalog.{database}.universal_credit"

write_timeseries(spark, uc_df, table_name, "calendar_year")
job.commit()

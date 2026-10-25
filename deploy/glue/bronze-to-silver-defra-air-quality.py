"""Bronze to silver for DEFRA population-weighted annual PM2.5 by local authority."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_snapshot
from pyspark.sql.functions import col, trim
from pyspark.sql.types import IntegerType, DoubleType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/defra/air-quality/",
    header=True,
    inferSchema=False,
)

air_quality_df = df.select(
    trim(col("calendar_year")).cast(IntegerType()).alias("calendar_year"),
    trim(col("geography_code")).alias("geography_code"),
    trim(col("geography_name")).alias("geography_name"),
    col("pm25_total").cast(DoubleType()).alias("pm25_total"),
    col("pm25_non_anthropogenic").cast(DoubleType()).alias("pm25_non_anthropogenic"),
    col("pm25_anthropogenic").cast(DoubleType()).alias("pm25_anthropogenic"),
).filter(
    col("calendar_year").isNotNull() & col("geography_code").isNotNull()
)

table_name = f"glue_catalog.{database}.air_quality"

# Bronze holds every year in one file; the table is replaced in full, dropping years no longer ingested.
write_snapshot(spark, air_quality_df, table_name, partition_col="calendar_year")
job.commit()

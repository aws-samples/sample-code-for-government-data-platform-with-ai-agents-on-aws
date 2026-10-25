"""Bronze to silver for the UK House Price Index average prices by area and month."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, to_date, year as spark_year, month as spark_month
from pyspark.sql.types import StructType, StructField, StringType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

schema = StructType([
    StructField("date", StringType()),
    StructField("region_name", StringType()),
    StructField("area_code", StringType()),
    StructField("average_price", StringType()),
    StructField("monthly_change", StringType()),
    StructField("annual_change", StringType()),
    StructField("average_price_sa", StringType()),
])

bronze_path = f"s3://{bucket}/bronze/ons/hpi/"
df = spark.read.option("header", "true").schema(schema).csv(bronze_path)

hpi_df = df.select(
    to_date(col("date"), "yyyy-MM-dd").alias("date"),
    trim(col("region_name")).alias("geography_name"),
    trim(col("area_code")).alias("geography_code"),
    col("average_price").cast("double").alias("average_price"),
    col("monthly_change").cast("double").alias("monthly_change_pct"),
    col("annual_change").cast("double").alias("annual_change_pct"),
    col("average_price_sa").cast("double").alias("average_price_sa"),
).withColumn("calendar_year", spark_year(col("date"))) \
 .withColumn("calendar_month", spark_month(col("date")))

hpi_df = hpi_df.filter(
    col("geography_code").isNotNull() & col("average_price").isNotNull()
)

table_name = f"glue_catalog.{database}.hpi"

write_timeseries(spark, hpi_df, table_name, "calendar_year")

job.commit()

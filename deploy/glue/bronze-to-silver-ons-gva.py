"""Bronze to silver for ONS GVA by industry by local authority, from the ONS beta API CSV."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim
from pyspark.sql.types import StructType, StructField, StringType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

schema = StructType([
    StructField("gva_value", StringType()),
    StructField("data_marking", StringType()),
    StructField("calendar_year_code", StringType()),
    StructField("calendar_year", StringType()),
    StructField("geography_code", StringType()),
    StructField("geography_name", StringType()),
    StructField("sic_code", StringType()),
    StructField("industry", StringType()),
    StructField("price_type_code", StringType()),
    StructField("price_type", StringType()),
])

bronze_path = f"s3://{bucket}/bronze/ons/gva/"
df = spark.read.option("header", "true").schema(schema).csv(bronze_path)

gva_df = df.select(
    col("gva_value").cast("double").alias("gva_value"),
    col("data_marking"),
    trim(col("calendar_year")).alias("calendar_year"),
    col("geography_code"),
    col("geography_name"),
    col("sic_code"),
    col("industry"),
    col("price_type_code"),
    col("price_type"),
)

gva_df = gva_df.filter(col("gva_value").isNotNull())

table_name = f"glue_catalog.{database}.gva"

write_timeseries(spark, gva_df, table_name, "calendar_year")

job.commit()

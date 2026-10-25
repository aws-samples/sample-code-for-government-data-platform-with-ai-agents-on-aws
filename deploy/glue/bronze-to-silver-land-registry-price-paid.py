"""Bronze to silver for HM Land Registry price paid transactions, from the headerless yearly CSVs."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, drop_duplicate_ids, start_job, write_timeseries
from pyspark.sql.functions import col, to_date, trim, regexp_replace
from pyspark.sql.types import StructType, StructField, StringType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# The CSV has no header row
schema = StructType([
    StructField("transaction_id", StringType()),
    StructField("price", StringType()),
    StructField("date_of_transfer", StringType()),
    StructField("postcode", StringType()),
    StructField("property_type", StringType()),
    StructField("old_new", StringType()),
    StructField("duration", StringType()),
    StructField("paon", StringType()),
    StructField("saon", StringType()),
    StructField("street", StringType()),
    StructField("locality", StringType()),
    StructField("town_city", StringType()),
    StructField("district", StringType()),
    StructField("county", StringType()),
    StructField("ppd_category", StringType()),
    StructField("record_status", StringType()),
])

bronze_path = f"s3://{bucket}/bronze/land-registry/price-paid/"
df = spark.read.option("header", "false").schema(schema).csv(bronze_path)

price_paid_df = df.select(
    regexp_replace(col("transaction_id"), "[{}]", "").alias("transaction_id"),
    col("price").cast("long"),
    to_date(col("date_of_transfer"), "yyyy-MM-dd HH:mm").alias("date_of_transfer"),
    trim(col("postcode")).alias("postcode"),
    col("property_type"),
    col("old_new"),
    col("duration"),
    trim(col("paon")).alias("paon"),
    trim(col("saon")).alias("saon"),
    trim(col("street")).alias("street"),
    trim(col("locality")).alias("locality"),
    trim(col("town_city")).alias("town_city"),
    trim(col("district")).alias("district"),
    trim(col("county")).alias("county"),
    col("ppd_category"),
    col("record_status"),
    col("year")  # calendar_year comes from the year= folder in the path
)

price_paid_df = price_paid_df.filter(
    col("transaction_id").isNotNull() & col("price").isNotNull()
)

# A transaction re-released by Land Registry appears in more than one yearly file
price_paid_df = drop_duplicate_ids(price_paid_df, "transaction_id", "price_paid")

table_name = f"glue_catalog.{database}.price_paid"

write_timeseries(spark, price_paid_df, table_name, "year")

job.commit()

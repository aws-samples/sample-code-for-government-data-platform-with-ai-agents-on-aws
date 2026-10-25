"""Bronze to silver for Police API street-level crime, from the monthly JSONL files per force."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, drop_duplicate_ids, start_job, write_timeseries
from pyspark.sql.functions import col, concat, lit, to_date, lpad

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

bronze_path = f"s3://{bucket}/bronze/police/crime/"
df = spark.read.json(bronze_path)

# The year=/month= partition folders shadow the JSON month field; month is rebuilt from them
crimes_df = df.select(
    col("id").cast("bigint"),
    col("persistent_id"),
    col("category"),
    concat(col("year"), lit("-"), lpad(col("month").cast("string"), 2, "0")).alias("month"),
    col("location_type"),
    col("location_subtype"),
    col("context"),
    col("location.latitude").cast("double").alias("latitude"),
    col("location.longitude").cast("double").alias("longitude"),
    col("location.street.id").cast("bigint").alias("street_id"),
    col("location.street.name").alias("street_name"),
    col("outcome_status.category").alias("outcome_category"),
    to_date(concat(col("outcome_status.date"), lit("-01"))).alias("outcome_date")
)

# The same crime can appear in more than one monthly file when its outcome is updated
crimes_df = drop_duplicate_ids(crimes_df, "id", "crimes")

table_name = f"glue_catalog.{database}.crimes"

write_timeseries(spark, crimes_df, table_name, "month")

job.commit()

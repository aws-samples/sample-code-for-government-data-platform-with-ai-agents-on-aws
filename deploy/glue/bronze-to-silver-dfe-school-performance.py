"""Bronze to silver for DfE KS4 attainment by pupil characteristics and geography (Explore Education Statistics API)."""
import re

from glue_common import SILVER_JOB_ARGS, configure_catalog, latest_object, start_job, to_number, write_snapshot
from pyspark.sql.functions import col, trim

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# Each DfE version holds every published year; the newest file replaces the table.
df = spark.read.option("header", "true").csv(latest_object(bucket, "bronze/dfe/school-performance/"))

measure = re.compile(r"(_count|_sum|_average|_total|_percent|_ci)$")
school_df = df.select([
    to_number(c).alias(c) if measure.search(c) else trim(col(c)).alias(c)
    for c in df.columns if not c.startswith("_")
])

write_snapshot(spark, school_df, f"glue_catalog.{database}.school_performance", partition_col="time_period")

job.commit()

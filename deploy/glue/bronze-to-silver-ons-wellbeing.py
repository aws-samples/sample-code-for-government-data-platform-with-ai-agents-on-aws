"""Bronze to silver for ONS personal wellbeing by local authority and year."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

bronze_path = f"s3://{bucket}/bronze/ons/wellbeing/"
df = spark.read.option("header", "true").csv(bronze_path)

wellbeing_df = df.select(
    col("v4_3").cast("double").alias("value"),
    trim(col("`Data marking`")).alias("data_marking"),
    col("`Lower limit`").cast("double").alias("lower_limit"),
    col("`Upper limit`").cast("double").alias("upper_limit"),
    col("`yyyy-yy`").alias("period"),
    col("`administrative-geography`").alias("geography_code"),
    col("Geography").alias("geography_name"),
    col("`measure-of-wellbeing`").alias("measure_code"),
    col("MeasureOfWellbeing").alias("measure_name"),
    col("`wellbeing-estimate`").alias("estimate_code"),
    col("Estimate").alias("estimate_name")
)

# Suppressed and missing values carry a data marking instead of a number
wellbeing_df = wellbeing_df.filter(
    (col("data_marking").isNull()) | (col("data_marking") == "")
)

table_name = f"glue_catalog.{database}.wellbeing"

write_timeseries(spark, wellbeing_df, table_name, "period")

job.commit()

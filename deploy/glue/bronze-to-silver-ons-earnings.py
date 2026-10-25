"""Bronze to silver for ONS ASHE earnings and hours by local authority, sex and working pattern."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim
from pyspark.sql.types import StructType, StructField, StringType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# The CSV repeats column names in different cases (sex, Sex); a positional schema stops Spark renaming them
schema = StructType([
    StructField("value", StringType()),
    StructField("data_marking", StringType()),
    StructField("cv", StringType()),
    StructField("calendar_year_code", StringType()),
    StructField("calendar_year", StringType()),
    StructField("geography_code", StringType()),
    StructField("geography_name", StringType()),
    StructField("percentile_code", StringType()),
    StructField("percentile", StringType()),
    StructField("sex_code", StringType()),
    StructField("sex", StringType()),
    StructField("working_pattern_code", StringType()),
    StructField("working_pattern", StringType()),
    StructField("measure_code", StringType()),
    StructField("measure", StringType()),
    StructField("workplace_residence_code", StringType()),
    StructField("workplace_residence", StringType()),
])

bronze_path = f"s3://{bucket}/bronze/ons/earnings/"
df = spark.read.option("header", "true").schema(schema).csv(bronze_path)

earnings_df = df.select(
    col("value").cast("double").alias("value"),
    col("data_marking"),
    col("cv").cast("double").alias("coefficient_of_variation"),
    trim(col("calendar_year")).alias("time_period"),
    col("calendar_year_code").alias("calendar_year"),
    col("geography_code"),
    col("geography_name"),
    col("percentile_code"),
    col("percentile"),
    col("sex_code"),
    col("sex"),
    col("working_pattern_code"),
    col("working_pattern"),
    col("measure_code"),
    col("measure"),
    col("workplace_residence_code"),
    col("workplace_residence"),
)

# Rows with neither a value nor a data marking are blank
earnings_df = earnings_df.filter(
    col("value").isNotNull() | col("data_marking").isNotNull()
)

# Each ASHE edition repeats some earlier years' rows unchanged
earnings_df = earnings_df.dropDuplicates()

table_name = f"glue_catalog.{database}.earnings"

write_timeseries(spark, earnings_df, table_name, "time_period")

job.commit()

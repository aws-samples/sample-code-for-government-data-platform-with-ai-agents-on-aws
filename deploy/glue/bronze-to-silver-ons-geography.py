"""Bronze to silver for the geography reference tables: centroids, region mapping, postcode-to-council and council code history."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_snapshot
from pyspark.sql.functions import col, to_date, trim
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

schema = StructType([
    StructField("geography_code", StringType()),
    StructField("geography_name", StringType()),
    StructField("latitude", DoubleType()),
    StructField("longitude", DoubleType()),
])

df = spark.read.csv(
    f"s3://{bucket}/bronze/ons/geography/lad-centroids.csv",
    header=True,
    schema=schema,
)

geography_df = df.select(
    trim(col("geography_code")).alias("geography_code"),
    trim(col("geography_name")).alias("geography_name"),
    col("latitude"),
    col("longitude"),
).filter(col("geography_code").isNotNull())

table_name = f"glue_catalog.{database}.geography_centroids"

write_snapshot(spark, geography_df, table_name)

# Council to region mapping
rgn_df = spark.read.csv(
    f"s3://{bucket}/bronze/ons/geography/lad-to-region.csv",
    header=True,
    schema=StructType([
        StructField("geography_code", StringType()),
        StructField("geography_name", StringType()),
        StructField("region_code", StringType()),
        StructField("region_name", StringType()),
    ]),
).select(
    trim(col("geography_code")).alias("geography_code"),
    trim(col("geography_name")).alias("geography_name"),
    trim(col("region_code")).alias("region_code"),
    trim(col("region_name")).alias("region_name"),
).filter(col("geography_code").isNotNull())

write_snapshot(spark, rgn_df, f"glue_catalog.{database}.lad_to_region")

# Postcode to council lookup, from the ONS National Statistics Postcode Lookup
pc_df = spark.read.csv(
    f"s3://{bucket}/bronze/ons/geography/postcode-to-la.csv",
    header=True,
    schema=StructType([
        StructField("postcode", StringType()),
        StructField("geography_code", StringType()),
    ]),
).select(
    trim(col("postcode")).alias("postcode"),
    trim(col("geography_code")).alias("geography_code"),
).filter(col("postcode").isNotNull() & col("geography_code").isNotNull())

# allow_drop removes the geography_name column, which the NSPL never filled
write_snapshot(spark, pc_df, f"glue_catalog.{database}.postcode_to_la", allow_drop=True)

# Council code changes, from the ONS Code History Database
history_df = spark.read.csv(
    f"s3://{bucket}/bronze/ons/geography/la-code-history.csv",
    header=True,
    schema=StructType([
        StructField("old_code", StringType()),
        StructField("old_name", StringType()),
        StructField("current_code", StringType()),
        StructField("current_name", StringType()),
        StructField("changed_on", StringType()),
        StructField("merged", StringType()),
    ]),
).select(
    trim(col("old_code")).alias("old_code"),
    trim(col("old_name")).alias("old_name"),
    trim(col("current_code")).alias("current_code"),
    trim(col("current_name")).alias("current_name"),
    to_date(col("changed_on")).alias("changed_on"),
    (col("merged") == "True").alias("merged"),
).filter(col("old_code").isNotNull() & col("current_code").isNotNull())

write_snapshot(spark, history_df, f"glue_catalog.{database}.la_code_history")

job.commit()

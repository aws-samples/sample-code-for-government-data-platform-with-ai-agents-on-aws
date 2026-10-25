"""Bronze to silver for DfT road traffic by local authority, joined to the DfT lookup for ONS codes."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col
from pyspark.sql.types import (
    IntegerType, LongType, DoubleType
)

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# JSON arrays need multiLine
la_df = spark.read.option("multiLine", True).json(f"s3://{bucket}/bronze/dft/road-traffic/local-authorities.json")
la_lookup = la_df.select(
    col("id").alias("la_id"),
    col("name").alias("la_name"),
    col("ons_code").alias("geography_code"),
)

traffic_df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/dft/road-traffic/local-authority-traffic.json"
)

road_traffic = traffic_df.join(
    la_lookup,
    traffic_df["local_authority_id"] == la_lookup["la_id"],
    "left",
).select(
    col("geography_code"),
    col("la_name").alias("geography_name"),
    col("year").cast(IntegerType()).alias("calendar_year"),
    col("total_link_length_km").cast(DoubleType()),
    col("total_link_length_miles").cast(DoubleType()),
    col("cars_and_taxis").cast(LongType()),
    col("all_motor_vehicles").cast(LongType()),
)

road_traffic = road_traffic.filter(col("geography_code").isNotNull())

table_name = f"glue_catalog.{database}.road_traffic"

write_timeseries(spark, road_traffic, table_name, "calendar_year")

job.commit()

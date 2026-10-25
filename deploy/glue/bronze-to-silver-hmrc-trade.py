"""Bronze to silver for HMRC Regional Trade Statistics, with region, country and flow type ids resolved to names."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, floor, trim
from pyspark.sql.types import IntegerType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# JSON arrays need multiLine
regions_df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/hmrc/trade/regions.json"
).select(
    col("RegionId").cast(IntegerType()).alias("region_id"),
    trim(col("RegionName")).alias("region_name"),
    trim(col("RegionGroupName")).alias("region_group"),
)

countries_df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/hmrc/trade/countries.json"
).select(
    col("CountryId").cast(IntegerType()).alias("country_id"),
    trim(col("CountryName")).alias("country_name"),
    trim(col("CountryCodeAlpha")).alias("country_code"),
)

flow_types_df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/hmrc/trade/flow-types.json"
).select(
    col("FlowTypeId").cast(IntegerType()).alias("flow_type_id"),
    trim(col("FlowTypeDescription")).alias("flow_type"),
)

rts_df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/hmrc/trade/rts/"
)

trade = rts_df \
    .join(regions_df, rts_df["GovRegionId"] == regions_df["region_id"], "left") \
    .join(countries_df, rts_df["CountryId"] == countries_df["country_id"], "left") \
    .join(flow_types_df, rts_df["FlowTypeId"] == flow_types_df["flow_type_id"], "left") \
    .select(
        col("MonthId").cast(IntegerType()).alias("month_id"),
        floor(col("MonthId") / 100).cast(IntegerType()).alias("calendar_year"),
        (col("MonthId") % 100).cast(IntegerType()).alias("month"),
        col("region_name"),
        col("region_group"),
        col("GovRegionId").cast(IntegerType()).alias("region_id"),
        col("country_name"),
        col("country_code"),
        col("flow_type"),
        col("CommoditySitc2Id").cast(IntegerType()).alias("sitc2_id"),
        col("Value").alias("trade_value"),
        col("NetMass").alias("net_mass_kg"),
    )

# Drop rows with no region, and HMRC's unallocated regions
trade = trade.filter(
    col("region_name").isNotNull() &
    ~col("region_name").startswith("Unallocated")
)

table_name = f"glue_catalog.{database}.trade"

write_timeseries(spark, trade, table_name, "calendar_year")

job.commit()

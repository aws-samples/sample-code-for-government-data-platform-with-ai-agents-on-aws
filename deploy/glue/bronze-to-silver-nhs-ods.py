"""Bronze to silver for NHS ODS organisations, with geography_code from the postcode-to-council lookup."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, trim, upper, input_file_name, regexp_extract
from pyspark.sql.types import StructType, StructField, StringType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# Every org type and snapshot: bronze/nhs/ods/{org_type}/snapshot_date=YYYY-MM-DD/organisations.json
df = spark.read.option("multiLine", True).json(
    f"s3://{bucket}/bronze/nhs/ods/*/snapshot_date=*/organisations.json"
)

df = df.withColumn("_path", input_file_name())
df = df.withColumn(
    "org_type",
    regexp_extract(col("_path"), r"bronze/nhs/ods/([^/]+)/snapshot_date=", 1)
).withColumn(
    "snapshot_date",
    regexp_extract(col("_path"), r"snapshot_date=(\d{4}-\d{2}-\d{2})", 1)
).drop("_path")

orgs = df.select(
    col("OrgId").alias("org_id"),
    col("Name").alias("org_name"),
    col("Status").alias("status"),
    col("PrimaryRoleId").alias("primary_role_id"),
    col("PrimaryRoleDescription").alias("primary_role_description"),
    trim(upper(col("PostCode"))).alias("postcode"),
    col("LastChangeDate").alias("last_change_date"),
    col("org_type"),
    col("snapshot_date"),
).filter(col("org_id").isNotNull())

# geography_code from the ONS postcode-to-LA lookup; a missing lookup fails the job rather than writing every code as null
postcode_la = spark.read.csv(
    f"s3://{bucket}/bronze/ons/geography/postcode-to-la.csv",
    header=True,
    schema=StructType([
        StructField("postcode", StringType()),
        StructField("geography_code", StringType()),
        StructField("geography_name", StringType()),
    ]),
).select(
    trim(upper(col("postcode"))).alias("_postcode"),
    trim(col("geography_code")).alias("geography_code"),
    trim(col("geography_name")).alias("geography_name"),
)
orgs = orgs.join(postcode_la, orgs["postcode"] == postcode_la["_postcode"], "left").drop("_postcode")

table_name = f"glue_catalog.{database}.nhs_ods_organisations"

write_timeseries(spark, orgs, table_name, "snapshot_date")
job.commit()

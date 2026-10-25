"""Bronze to silver for DfE KS4 school-level performance tables (Explore Education Statistics API)."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, latest_object, start_job, to_number, write_snapshot
from pyspark.sql.functions import col, trim

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

# Each DfE version holds the years DfE still publishes; the newest file replaces the table.
df = spark.read.csv(latest_object(bucket, "bronze/dfe/school-detail/"), header=True, inferSchema=False)

dimensions = [
    "time_period", "time_identifier", "geographic_level", "school_urn", "school_name", "school_laestab",
    "new_la_code", "la_name", "version", "establishment_type_group", "breakdown_topic", "breakdown",
    "sex", "disadvantage_status", "first_language", "prior_attainment", "mobility",
]
measures = {
    "pupil_count": "pupil_count",
    "attainment8_average": "attainment8_average",
    "progress8_average": "progress8_average",
    "progress8_lower_95_ci": "progress8_lower_ci",
    "progress8_upper_95_ci": "progress8_upper_ci",
    "engmath_94_percent": "engmath_94_percent",
    "engmath_95_percent": "engmath_95_percent",
}
school_detail = df.select(
    [trim(col(c)).alias(c) for c in dimensions]
    + [to_number(source).alias(name) for source, name in measures.items()]
).filter(col("geographic_level") == "School")

write_snapshot(spark, school_detail, f"glue_catalog.{database}.school_detail", partition_col="time_period")

job.commit()

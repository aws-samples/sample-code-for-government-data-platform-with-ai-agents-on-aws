"""Bronze to silver for NHS England RTT waiting times: incomplete pathways aggregated to commissioner and month."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
import re
from functools import reduce
from operator import add
from pyspark.sql.functions import (
    coalesce, col, trim, regexp_extract, regexp_replace, lit,
    sum as spark_sum, when, round as spark_round,
)
from pyspark.sql.types import IntegerType, FloatType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/nhs/rtt-waiting-times/",
    header=True,
    inferSchema=False,
)

# Column names to snake_case
def norm(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower().strip()).strip('_')

renamed = df
for c in df.columns:
    renamed = renamed.withColumnRenamed(c, norm(c))

cols = renamed.columns

# Week-band columns and the total arrive as text with thousands separators; a blank band means no patients and counts as 0
week_cols = [c for c in cols if re.match(r'gt_\d+', c)]
total_col = "total_all" if "total_all" in cols else "total"

for c in week_cols + [total_col]:
    renamed = renamed.withColumn(c, coalesce(regexp_replace(col(c), r",", "").cast(FloatType()), lit(0.0)))

# period is "RTT-April-2025": year 2025, month April
renamed = renamed.withColumn(
    "calendar_year",
    regexp_extract(col("period"), r"(\d{4})", 1).cast(IntegerType())
)
renamed = renamed.withColumn(
    "month_name",
    regexp_extract(col("period"), r"RTT-(\w+)-\d{4}", 1)
)

filtered = renamed.filter(
    col("rtt_part_description").contains("Incomplete") &
    col("calendar_year").isNotNull() &
    (col("month_name") != "") &
    col("commissioner_org_code").isNotNull() &
    (trim(col("commissioner_org_code")) != "")
)

# Patients waiting over 18 and over 52 weeks, from the week-band columns
over_18_cols = [c for c in week_cols if re.match(r'gt_(1[89]|[2-9]\d|1\d{2})_', c)]
over_52_cols = [c for c in week_cols if re.match(r'gt_(5[2-9]|[6-9]\d|1\d{2})_', c)]


def sum_cols(dataframe, cols_list, alias):
    if not cols_list:
        return dataframe.withColumn(alias, lit(0.0))
    expr = reduce(add, [col(c) for c in cols_list])
    return dataframe.withColumn(alias, expr)


filtered = sum_cols(filtered, over_18_cols, "over_18_weeks")
filtered = sum_cols(filtered, over_52_cols, "over_52_weeks")

# One row per commissioner and month
agg = filtered.groupBy(
    "calendar_year",
    "month_name",
    "commissioner_org_code",
    "commissioner_org_name",
    "commissioner_parent_org_code",
    "commissioner_parent_name",
).agg(
    spark_sum(col(total_col)).alias("total_waiting"),
    spark_sum(col("over_18_weeks")).alias("waiting_over_18_weeks"),
    spark_sum(col("over_52_weeks")).alias("waiting_over_52_weeks"),
)

agg = agg.withColumn(
    "pct_over_18_weeks",
    spark_round(
        when(col("total_waiting") > 0,
             col("waiting_over_18_weeks") / col("total_waiting") * 100
        ).otherwise(None),
        1
    )
)

table_name = f"glue_catalog.{database}.nhs_rtt_waiting_times"

write_timeseries(spark, agg, table_name, "calendar_year")
job.commit()

"""Bronze to silver for ONS mid-year population estimates by area, sex and single year of age (NOMIS NM_2002_1)."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_timeseries
from pyspark.sql.functions import col, lit, lower, trim, when

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.option("header", "true").csv(f"s3://{bucket}/bronze/ons/population/population-by-la.csv")

gender = col("GENDER").cast("int")
c_age = col("C_AGE").cast("int")
sex = when(gender == 0, lit("All")).when(gender == 1, lit("Male")).when(gender == 2, lit("Female"))
# NOMIS age codes: 101-190 are ages 0 to 89, 191 is 90+, 200 is all ages
age = when(c_age == 200, lit("Total")).when(c_age == 191, lit("90+")).otherwise((c_age - 101).cast("string"))

population_df = df.select(
    col("OBS_VALUE").cast("long").alias("population"),
    trim(col("DATE_NAME")).alias("time_period"),
    trim(col("DATE_NAME")).alias("calendar_year"),
    trim(col("GEOGRAPHY_CODE")).alias("geography_code"),
    trim(col("GEOGRAPHY_NAME")).alias("geography_name"),
    lower(sex).alias("sex_code"),
    sex.alias("sex"),
    lower(age).alias("age_code"),
    age.alias("age"),
).filter(col("population").isNotNull() & col("sex").isNotNull())

# Regions and countries overlap for Wales, Scotland and Northern Ireland, which NOMIS returns twice
population_df = population_df.dropDuplicates(["geography_code", "time_period", "sex", "age"])
# Inner and Outer London (E13) come with the metropolitan counties; no other source has E13 rows
population_df = population_df.filter(~col("geography_code").startswith("E13"))

table_name = f"glue_catalog.{database}.population"

write_timeseries(spark, population_df, table_name, "time_period")

job.commit()

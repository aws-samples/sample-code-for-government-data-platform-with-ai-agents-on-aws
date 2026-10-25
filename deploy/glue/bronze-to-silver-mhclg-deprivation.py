"""Bronze to silver for the English Indices of Deprivation 2025 by LSOA (file 7)."""
from glue_common import SILVER_JOB_ARGS, configure_catalog, start_job, write_snapshot
from pyspark.sql.functions import col, trim
from pyspark.sql.types import IntegerType, DoubleType

args, spark, job = start_job(SILVER_JOB_ARGS)
bucket = args['DATALAKE_BUCKET']
database = args['DATABASE_NAME']
configure_catalog(spark, "glue_catalog", args['S3_TABLE_BUCKET_NAME_SILVER'])

df = spark.read.csv(
    f"s3://{bucket}/bronze/mhclg/deprivation/",
    header=True,
    inferSchema=False,
    quote='"',
)

# File 7 of the IMD release (2021 LSOA / 2024 LAD codes), per GOV.UK documentation
deprivation_df = df.select(
    trim(col("`LSOA code (2021)`")).alias("lsoa_code"),
    trim(col("`LSOA name (2021)`")).alias("lsoa_name"),
    trim(col("`Local Authority District code (2024)`")).alias("la_code"),
    trim(col("`Local Authority District name (2024)`")).alias("la_name"),
    col("`Index of Multiple Deprivation (IMD) Rank (where 1 is most deprived)`").cast(IntegerType()).alias("imd_rank"),
    col("`Index of Multiple Deprivation (IMD) Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("imd_decile"),
    col("`Index of Multiple Deprivation (IMD) Score`").cast(DoubleType()).alias("imd_score"),
    col("`Income Score (rate)`").cast(DoubleType()).alias("income_score"),
    col("`Income Rank (where 1 is most deprived)`").cast(IntegerType()).alias("income_rank"),
    col("`Income Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("income_decile"),
    col("`Employment Score (rate)`").cast(DoubleType()).alias("employment_score"),
    col("`Employment Rank (where 1 is most deprived)`").cast(IntegerType()).alias("employment_rank"),
    col("`Employment Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("employment_decile"),
    col("`Education, Skills and Training Score`").cast(DoubleType()).alias("education_score"),
    col("`Education, Skills and Training Rank (where 1 is most deprived)`").cast(IntegerType()).alias("education_rank"),
    col("`Education, Skills and Training Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("education_decile"),
    col("`Health Deprivation and Disability Score`").cast(DoubleType()).alias("health_score"),
    col("`Health Deprivation and Disability Rank (where 1 is most deprived)`").cast(IntegerType()).alias("health_rank"),
    col("`Health Deprivation and Disability Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("health_decile"),
    col("`Crime Score`").cast(DoubleType()).alias("crime_score"),
    col("`Crime Rank (where 1 is most deprived)`").cast(IntegerType()).alias("crime_rank"),
    col("`Crime Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("crime_decile"),
    col("`Barriers to Housing and Services Score`").cast(DoubleType()).alias("housing_score"),
    col("`Barriers to Housing and Services Rank (where 1 is most deprived)`").cast(IntegerType()).alias("housing_rank"),
    col("`Barriers to Housing and Services Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("housing_decile"),
    col("`Living Environment Score`").cast(DoubleType()).alias("living_env_score"),
    col("`Living Environment Rank (where 1 is most deprived)`").cast(IntegerType()).alias("living_env_rank"),
    col("`Living Environment Decile (where 1 is most deprived 10% of LSOAs)`").cast(IntegerType()).alias("living_env_decile"),
    col("`Total population: mid 2022`").cast(IntegerType()).alias("total_population"),
).filter(col("lsoa_code").isNotNull())

table_name = f"glue_catalog.{database}.deprivation"

write_snapshot(spark, deprivation_df, table_name)
job.commit()

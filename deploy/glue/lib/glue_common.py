"""Shared job setup and Iceberg write helpers for the Glue ETL jobs."""
import logging
import os
import sys

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import col, lit, trim, when

SILVER_JOB_ARGS = ("DATALAKE_BUCKET", "DATABASE_NAME", "S3_TABLE_BUCKET_NAME_SILVER")

logger = logging.getLogger("glue_common")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def start_job(arg_names=()):
    """Resolve job arguments, start the Glue job and return (args, spark, job)."""
    args = getResolvedOptions(sys.argv, ["JOB_NAME", *arg_names])
    glue_context = GlueContext(SparkContext.getOrCreate())
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    return args, glue_context.spark_session, job


def aws_region():
    """Return the job's AWS region, failing rather than guessing one."""
    region = (
        boto3.session.Session().region_name
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    if not region:
        raise RuntimeError("No AWS region set for the Glue job")
    return region


def configure_catalog(spark, catalog, table_bucket):
    """Point a Spark catalog at an S3 Tables bucket through the S3 Tables Iceberg REST endpoint."""
    region = aws_region()
    account_id = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    settings = {
        "": "org.apache.iceberg.spark.SparkCatalog",
        ".type": "rest",
        ".uri": f"https://s3tables.{region}.amazonaws.com/iceberg",
        ".warehouse": f"arn:aws:s3tables:{region}:{account_id}:bucket/{table_bucket}",
        ".rest.sigv4-enabled": "true",
        ".rest.signing-name": "s3tables",
        ".rest.signing-region": region,
        ".io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
    }
    for key, value in settings.items():
        spark.conf.set(f"spark.sql.catalog.{catalog}{key}", value)


def latest_object(bucket, prefix):
    """s3:// path of the newest file under prefix, for sources where each new file supersedes the earlier ones."""
    s3 = boto3.client("s3", region_name=aws_region())
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    files = [o for page in pages for o in page.get("Contents", []) if not o["Key"].endswith("/")]
    if not files:
        raise RuntimeError(f"No files under s3://{bucket}/{prefix}")
    latest = max(files, key=lambda o: o["LastModified"])
    logger.info(f"Reading {latest['Key']}, the newest of {len(files)} files under {prefix}")
    return f"s3://{bucket}/{latest['Key']}"


def to_number(column):
    """A text column as a double, with suppression codes such as DfE's c, x, z and low, and any other non-number, as null."""
    value = trim(col(column))
    return when(value.rlike(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$"), value.cast("double"))


def drop_duplicate_ids(df, id_col, name):
    """Keep one row per id, logging how many were dropped."""
    before = df.count()
    df = df.dropDuplicates([id_col])
    dropped = before - df.count()
    if dropped:
        logger.warning(f"{name}: dropped {dropped} rows sharing an existing {id_col}")
    return df


def _quote(name):
    """Backtick-quote a column name for Spark SQL DDL."""
    return "`" + name.replace("`", "``") + "`"


def _create_table(spark, df, table, partition_col=None):
    columns = ", ".join(f"{_quote(f.name)} {f.dataType.simpleString()}" for f in df.schema.fields)
    partition = f" PARTITIONED BY ({_quote(partition_col)})" if partition_col else ""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({columns}) USING iceberg{partition}")  # nosec B608, table name is a code constant and column names are quoted
    logger.info(f"Created {table}")


def _align_schema(spark, df, table, allow_drop):
    """Add the DataFrame's new columns to the table, and fill or drop table columns the DataFrame lacks."""
    existing = {f.name: f.dataType for f in spark.table(table).schema.fields}
    for name in [c for c in df.columns if c not in existing]:
        spark.sql(f"ALTER TABLE {table} ADD COLUMNS ({_quote(name)} {df.schema[name].dataType.simpleString()})")  # nosec B608, table name is a code constant and column names are quoted
        logger.info(f"{table}: added column {name}")
    changed = {c: (existing[c].simpleString(), df.schema[c].dataType.simpleString())
               for c in df.columns if c in existing and df.schema[c].dataType != existing[c]}
    if changed:
        logger.warning(f"{table}: column types differ from the table (table, new): {changed}")
    for name in [c for c in existing if c not in df.columns]:
        if allow_drop:
            spark.sql(f"ALTER TABLE {table} DROP COLUMN {_quote(name)}")  # nosec B608, table name is a code constant and column names are quoted
            logger.warning(f"{table}: dropped column {name}")
        else:
            df = df.withColumn(name, lit(None).cast(existing[name]))
            logger.warning(f"{table}: column {name} missing from this run, written as null and kept in the table")
    return df


def _log_written(spark, table):
    """Log and return the row count of the table's latest commit, from its snapshot summary."""
    latest = spark.sql(
        f"SELECT summary['added-records'] AS added FROM {table}.snapshots ORDER BY committed_at DESC LIMIT 1"  # nosec B608, table name is a code constant
    ).collect()
    added = int(latest[0]["added"] or 0) if latest else 0
    logger.info(f"Wrote {added} rows to {table}")
    return added


def write_timeseries(spark, df, table, partition_col, allow_drop=False):
    """Create or align the table, replace only the partitions present in df, and return the rows written."""
    if spark.catalog.tableExists(table):
        df = _align_schema(spark, df, table, allow_drop)
    else:
        _create_table(spark, df, table, partition_col)
    df.writeTo(table).overwritePartitions()
    return _log_written(spark, table)


def write_snapshot(spark, df, table, allow_drop=False, partition_col=None):
    """Create or align the table, replace all of its rows in a single commit, and return the rows written."""
    if spark.catalog.tableExists(table):
        df = _align_schema(spark, df, table, allow_drop)
    else:
        _create_table(spark, df, table, partition_col)
    df.writeTo(table).overwrite(lit(True))
    return _log_written(spark, table)

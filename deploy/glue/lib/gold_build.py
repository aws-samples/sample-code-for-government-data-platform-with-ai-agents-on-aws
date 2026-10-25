"""Builds the gold tables described in gold_tables: the shared helpers, the dims and facts that need real logic, the write, and the registry."""
import json
import logging
from datetime import datetime, timezone

import boto3
from glue_common import write_snapshot
from pyspark.errors import AnalysisException
from pyspark.sql.functions import (
    array, avg, broadcast, coalesce, col, concat, count, create_map, element_at, explode, expr, lit, regexp_replace,
    sequence, split, substring, sum as spark_sum, trim, upper, when,
)
from pyspark.sql.types import IntegerType

logger = logging.getLogger("gold_build")
logger.setLevel("INFO")

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


class Gold:
    """One run of the gold job: Spark, the catalogs, the council code history, and the result of every table built."""

    def __init__(self, spark, silver_db, gold_db, bucket, registry_table, ingest_schedules=None):
        self.spark = spark
        self.silver_db = silver_db
        self.gold_db = gold_db
        self.bucket = bucket
        self.registry_table = registry_table
        # source_id to its EventBridge cron, from local.ingest_sources in Terraform
        self.ingest_schedules = ingest_schedules or {}
        self.prefix = bucket.split("-datalake-")[0]
        self.results = {}
        self.frames = {}
        history = spark.table(f"glue_catalog.{silver_db}.la_code_history").collect()
        self.recoded = {r.old_code: r.current_code for r in history if not r.merged}
        self.merged = {r.old_code: (r.current_code, r.current_name) for r in history if r.merged}

    def read(self, table):
        return self.spark.table(f"glue_catalog.{self.silver_db}.{table}")

    # Council codes

    def apply_code_remap(self, df, col_name="geography_code"):
        """Replace codes of recoded areas (same area, new code) with their current code."""
        return df.withColumn(col_name, coalesce(_lookup(self.recoded)[col(col_name)], col(col_name)))

    def merge_into_current(self, df, measure_cols, name_col="geography_name", where=None):
        """Move rows of merged areas onto the current area's code and name, summing measure_cols; rows outside where keep their old code."""
        columns = df.columns
        old = col("geography_code")
        merge = old.isin(list(self.merged)) if where is None else old.isin(list(self.merged)) & where
        codes = _lookup({o: c for o, (c, _) in self.merged.items()})
        names = _lookup({o: n for o, (_, n) in self.merged.items()})
        df = df.withColumn(name_col, when(merge, names[old]).otherwise(col(name_col))).withColumn(
            "geography_code", when(merge, codes[old]).otherwise(old))
        keys = [c for c in columns if c not in measure_cols]
        return df.groupBy(*keys).agg(*[spark_sum(c).alias(c) for c in measure_cols]).select(columns)

    # Building and writing

    def build(self, spec):
        """Build one table from its spec and write it, recording success, skipped (silver table missing) or failed."""
        name = spec["gold_table"]
        try:
            if "build" in spec:
                df = getattr(self, f"build_{spec['build']}")()
            else:
                df = self.read(spec["silver_table"])
                if spec.get("filter"):
                    df = df.filter(spec["filter"])
                df = df.selectExpr(*spec["columns"])
                if spec.get("merge_measures"):
                    where = expr(spec["merge_where"]) if spec.get("merge_where") else None
                    df = self.merge_into_current(df, spec["merge_measures"], where=where)
            if spec.get("warn_null_periods"):
                self.warn_null_periods(name, df)
            if "geography_code" in df.columns:
                df = self.apply_code_remap(df)
            if name == "dim_geography":
                self.frames[name] = df
            # Gold is rebuilt in full from silver; the full replace also drops years that left the source
            rows = write_snapshot(self.spark, df, f"gold_catalog.{self.gold_db}.{name}", partition_col=spec.get("partition"))
            self.results[name] = {"status": "success", "rows": rows}
            logger.info(json.dumps({"table": name, "status": "success", "rows": rows}))
        except Exception as e:
            if isinstance(e, AnalysisException) and "TABLE_OR_VIEW_NOT_FOUND" in str(e):
                self.results[name] = {"status": "skipped", "error": str(e)}
                logger.warning(json.dumps({"table": name, "status": "skipped", "reason": "silver table not built yet"}))
            else:
                self.results[name] = {"status": "failed", "error": str(e)}
                logger.error(json.dumps({"table": name, "status": "failed", "error": str(e)}))
        return self.results[name]["status"]

    def warn_null_periods(self, name, df):
        """Unparseable date labels yield NULL period_yyyymm, which would drop from the area views unnoticed."""
        n = df.filter(col("period_yyyymm").isNull()).count()
        if n:
            logger.warning(json.dumps({"table": name, "null_period_yyyymm_rows": n}))

    # Dimensions

    def build_dim_geography(self):
        """Councils, counties, regions and countries with their centroids; geography_type from the ONS code prefix."""
        return self.read("geography_centroids").select("geography_code", "geography_name", "latitude", "longitude").withColumn(
            "geography_type",
            when(col("geography_code").rlike("^E0[6-9]|^W06"), lit("local_authority"))
            .when(col("geography_code").rlike("^E10"), lit("county"))
            .when(col("geography_code").rlike("^E1[12]"), lit("region"))
            .when(col("geography_code").rlike("^S12"), lit("scottish_council"))
            .when(col("geography_code").rlike("^N09"), lit("ni_district"))
            .when(col("geography_code").rlike("^[EKSNW]92|^K0[234]"), lit("country"))
            .otherwise(lit("other")),
        )

    def build_dim_time(self):
        """Month-grain calendar spine over the years of the core sources; period_yyyymm is the join key."""
        year_sources = {
            "crimes": "CAST(SUBSTRING(month, 1, 4) AS INT)", "population": "CAST(calendar_year AS INT)",
            "wellbeing": "CAST(SUBSTRING(period, 1, 4) AS INT)", "earnings": "CAST(calendar_year AS INT)",
            "school_performance": "CAST(SUBSTRING(time_period, 1, 4) AS INT) + 1", "price_paid": "CAST(year AS INT)",
            "road_traffic": "CAST(calendar_year AS INT)", "gva": "CAST(calendar_year AS INT)", "aps": "CAST(calendar_year AS INT)",
        }
        years = None
        for table, year in year_sources.items():
            df = self.read(table).selectExpr(f"{year} AS calendar_year").distinct()
            years = df if years is None else years.unionByName(df)
        years = years.distinct().filter(col("calendar_year").isNotNull())
        month_name = element_at(array(*[lit(m) for m in MONTH_NAMES]), col("calendar_month"))
        return years.select(col("calendar_year"), explode(sequence(lit(1), lit(12))).alias("calendar_month")).select(
            (col("calendar_year") * 100 + col("calendar_month")).cast(IntegerType()).alias("period_yyyymm"),
            col("calendar_year"),
            col("calendar_month"),
            month_name.alias("month_name"),
            (((col("calendar_month") - 1) / 3).cast(IntegerType()) + 1).alias("quarter"),
            # UK financial year ending year: March 2026 is FY 2025/26, which gives 2026
            when(col("calendar_month") >= 4, col("calendar_year") + 1).otherwise(col("calendar_year")).cast(IntegerType()).alias("fiscal_year"),
            ((col("calendar_year") / 10).cast(IntegerType()) * 10).alias("decade"),
            concat(month_name, lit(" "), col("calendar_year").cast("string")).alias("display_label"),
        )

    # Facts with joins or aggregation

    def build_crime(self):
        """Each crime assigned to a council by a point-in-polygon test on its own coordinates, then counted by type, month and street."""
        geojson = json.loads("".join(r.value for r in self.spark.read.text(f"s3://{self.bucket}/bronze/ons/geography/lad-boundaries.geojson").collect()))
        polygons = [(f["geometry"], f["properties"]["geography_code"], f["properties"].get("geography_name"))
                    for f in geojson.get("features", []) if f.get("properties", {}).get("geography_code")]
        if not polygons:
            raise RuntimeError("No council boundary polygons in lad-boundaries.geojson")
        broadcast_polygons = self.spark.sparkContext.broadcast(polygons)
        logger.info(f"Loaded {len(polygons)} council boundary polygons for the spatial join")

        def find_la(lat, lng):
            if lat is None or lng is None:
                return None
            from shapely.geometry import Point, shape
            from shapely.strtree import STRtree
            # The spatial index is built once per Python worker and kept on the function
            if not hasattr(find_la, "tree"):
                polys, meta = [], {}
                for geometry, code, name in broadcast_polygons.value:
                    try:
                        geom = shape(geometry)
                    except Exception:  # nosec B112, skips a malformed boundary polygon rather than failing every row
                        continue
                    polys.append(geom)
                    meta[id(geom)] = (code, name)
                find_la.tree, find_la.polys, find_la.meta = STRtree(polys), polys, meta
            point = Point(lng, lat)
            for idx in find_la.tree.query(point):
                geom = find_la.polys[idx]
                if geom.contains(point):
                    code, name = find_la.meta[id(geom)]
                    return f"{code}|{name}"
            return None

        from pyspark.sql.functions import udf
        from pyspark.sql.types import StringType
        matched = self.read("crimes").withColumn("_la", udf(find_la, StringType())(col("latitude"), col("longitude")))
        return matched.withColumn("geography_code", split(col("_la"), "\\|").getItem(0)).withColumn(
            "geography_name", split(col("_la"), "\\|").getItem(1),
        ).groupBy("category", "month", "street_name", "outcome_category", "geography_code", "geography_name").agg(
            count("*").alias("crime_count"),
            avg("latitude").alias("avg_latitude"),
            avg("longitude").alias("avg_longitude"),
        ).withColumn("calendar_year", substring(col("month"), 1, 4).cast(IntegerType())).withColumn(
            "period_yyyymm", regexp_replace(col("month"), "-", "").cast(IntegerType()))

    def build_school_performance(self):
        """KS4 results by education authority plus England's own row, every DfE breakdown kept."""
        national = col("geographic_level") == "National"
        return self.read("school_performance").filter(col("geographic_level").isin("Local authority", "National")).select(
            when(national, col("country_code")).otherwise(col("new_la_code")).alias("geography_code"),
            when(national, col("country_name")).otherwise(col("la_name")).alias("la_name"),
            (substring(col("time_period"), 1, 4).cast(IntegerType()) + 1).alias("calendar_year"),
            col("time_period"), col("time_identifier"), col("version"), col("breakdown_topic"),
            col("sex").alias("gender"), col("ethnicity_major").alias("ethnicity"), col("ethnicity_minor"),
            col("disadvantage_status").alias("disadvantage"), col("fsm_status").alias("fsm"), col("sen_provision").alias("sen"),
            *[col(c) for c in ("sen_status", "sen_primary_need", "first_language", "prior_attainment", "ks2_scaled_score_group",
                               "mobility", "young_carer", "school_admission_type", "school_religious_character")],
            col("pupil_count").cast("double").alias("t_cohort"),
            col("attainment8_average").cast("double").alias("avg_att8"),
            col("engmath_94_percent").cast("double").alias("pt_l2basics_94"),
            col("engmath_95_percent").cast("double").alias("pt_l2basics_95"),
        )

    def build_house_prices(self):
        """Sales by district, type and year. Each sale's council comes from its postcode, falling back to the district name."""
        postcode_la = self.read("postcode_to_la").select(col("postcode").alias("_postcode"), col("geography_code").alias("_postcode_la"))
        name_la = self.frames["dim_geography"].select(col("geography_code").alias("_name_la"), upper(col("geography_name")).alias("_upper_name"))
        sales = self.read("price_paid")
        sales = sales.join(postcode_la, upper(trim(sales["postcode"])) == col("_postcode"), "left").join(
            broadcast(name_la), upper(sales["district"]) == col("_upper_name"), "left",
        ).withColumn("geography_code", coalesce(col("_postcode_la"), col("_name_la")))
        # Recode before grouping, to land a postcode's old code and the name match's current code in one row
        sales = self.apply_code_remap(sales)
        prices = sales.groupBy("district", "county", "property_type", "old_new", "duration", "year", "geography_code").agg(
            count("*").alias("transaction_count"),
            expr("min(price)").alias("min_price"),
            expr("max(price)").alias("max_price"),
            avg("price").alias("avg_price"),
            expr("percentile_approx(price, 0.5)").alias("median_price"),
            spark_sum("price").alias("total_value"),
        ).withColumn("calendar_year", col("year").cast(IntegerType()))
        return prices.select([c for c in prices.columns if c != "geography_code"] + ["geography_code"])

    def build_deprivation(self):
        """IMD 2025 LSOA scores averaged to each council."""
        return self.read("deprivation").groupBy("la_code", "la_name").agg(
            avg("imd_score").alias("avg_imd_score"),
            avg("imd_rank").alias("avg_imd_rank"),
            count("*").alias("lsoa_count"),
            spark_sum(expr("CASE WHEN imd_decile = 1 THEN 1 ELSE 0 END")).alias("lsoas_in_most_deprived_decile"),
            *[avg(f"{d}_score").alias(f"avg_{d}_score") for d in ("income", "employment", "education", "health", "crime", "housing", "living_env")],
            spark_sum("total_population").alias("total_population"),
        ).withColumn("geography_code", col("la_code")).withColumn(
            "pct_most_deprived", col("lsoas_in_most_deprived_decile") / col("lsoa_count") * 100)

    # Registry

    def year_range(self, spec):
        """(min, max) years of the table just written, from the spec's year expression; (None, None) when it has none."""
        year = spec.get("year", "calendar_year")
        if isinstance(year, tuple):
            return year
        df = self.spark.table(f"gold_catalog.{self.gold_db}.{spec['gold_table']}")
        if year is None or (year == "calendar_year" and "calendar_year" not in df.columns):
            return None, None
        row = df.selectExpr(f"MIN({year}) AS lo", f"MAX({spec.get('year_end', year)}) AS hi").collect()[0]
        return (str(row.lo) if row.lo is not None else None), (str(row.hi) if row.hi is not None else None)

    def upsert_registry(self, spec):
        """Write the source's static metadata, year range and row count, and set silver_last_processed on its first build."""
        if not self.registry_table or "source_id" not in spec:
            return
        name = spec["gold_table"]
        lo, hi = self.year_range(spec)
        sets, vals = ["#n = :n"], {":n": spec["name"]}
        for key in ("department", "api_url", "update_frequency", "bronze_s3_prefix", "attribution"):
            sets.append(f"{key} = :{key}")
            vals[f":{key}"] = spec[key]
        sets += ["gold_tables = :gt", "glue_job_name = :gj", "row_count = :rc"]
        vals.update({":gt": [name, spec.get("rs_table", f"rs_{name}")], ":gj": f"{self.prefix}-glue-{spec['glue_job_name']}",
                     ":rc": self.results[name]["rows"]})
        if "view_columns" in spec:
            sets.append("view_columns = :vc")
            vals[":vc"] = spec["view_columns"]
        if lo is not None:
            sets += ["min_year = :mn", "max_year = :mx"]
            vals.update({":mn": lo, ":mx": hi})
        # Set silver_last_processed only on a source's first build (now, nothing newer exists yet); mark-silver-processed owns it after that, stamping the bronze time it was queued for
        sets.append("silver_last_processed = if_not_exists(silver_last_processed, :slp)")
        vals[":slp"] = datetime.now(timezone.utc).isoformat()
        removes = []
        if schedule := self.ingest_schedules.get(spec["source_id"]):
            sets.append("ingest_schedule = :is")
            vals[":is"] = schedule
        else:
            removes.append("ingest_schedule")
        try:
            boto3.resource("dynamodb").Table(self.registry_table).update_item(
                Key={"source_id": spec["source_id"]}, UpdateExpression="SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else ""),
                ExpressionAttributeValues=vals, ExpressionAttributeNames={"#n": "name"})
            logger.info(f"REGISTRY OK: {spec['source_id']} {lo}-{hi}, rows={self.results[name]['rows']}")
        except Exception as e:
            self.results[f"registry:{spec['source_id']}"] = {"status": "failed", "error": str(e)}
            logger.error(f"REGISTRY FAIL: {spec['source_id']}: {e}")


def _lookup(mapping):
    """Spark map literal from a Python dict."""
    return create_map(*[lit(v) for pair in mapping.items() for v in pair])

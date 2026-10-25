---
inclusion: always
---

# Data sources

UK public sector APIs are listed at https://www.api.gov.uk/#uk-public-sector-apis.

The DynamoDB data source registry (`{prefix}-data-source-registry`) is the live inventory of loaded sources, with API URLs, gold tables, year ranges and row counts. The gold Glue job writes it.

Copy an existing source rather than starting from scratch. `dwp-pip` is a good reference for a time-series source with an API key. Grep its identifiers (`dwp-pip`, `dwp_pip`, `fact_pip`, `pip_`) to see every file a source touches.

## Add a data source

### 1. Ingestion Lambda

- Add `deploy/lambda/ingest-<dept>-<name>/handler.py`. The pipeline zips the folder as it is, with no dependency install: the Python standard library, boto3 and the `common` layer (`deploy/lambda/layers/common/python/`) only.
- Use the layer rather than urllib and boto3 directly: `fetch.get`, `fetch.get_json` and `fetch.download` (one User-Agent, timeouts, retries on 5xx), `bronze.put`, `bronze.upload`, `bronze.sweep` and `bronze.report` for the write, the log line and the return value, and `nomis`, `ons` or `statxplore` for those APIs. Every `module "ingest_*"` block attaches it with `layers = [aws_lambda_layer_version.common.arn]`.
- Write raw files to `bronze/<dept>/<dataset>/` in the datalake bucket (`DATALAKE_BUCKET` env var).
- Add a `module "ingest_<dept>_<name>"` block to `deploy/terraform-live/21-ingest-lambdas.tf` using `./modules/lambda_function`. Copy `ingest_ons_earnings` (no key) or `ingest_dwp_pip` (API key). The module sets naming, tags, logs, X-Ray and KMS.
- If the API needs a key, add `API_KEYS_SECRET_ID` to the env vars and a `secretsmanager:GetSecretValue` statement, then store the key (see [API keys](#api-keys)).

### 2. Ingest orchestrator

- Add one entry to `local.ingest_sources` in `deploy/terraform-live/20-ingest-orchestrator.tf`: `<key> = { type = "lambda", arn = module.ingest_<dept>_<name>.function_arn, source_id = "<source-id>", schedule = null }`. The key is what you pass to the ingest Step Function; `source_id` is the one in `gold_tables.py`. The router, the Step Function's IAM and the schedules are all built from this map.
- To refresh on a timetable, set `schedule` to a cron at 06:00 UTC a few days after the publisher's usual release, e.g. `"cron(0 6 25 3,6,9,12 ? *)"`, with a trailing comment naming the release day. It creates `{prefix}-schedule-ingest-<key>`, grants the scheduler role, and the gold job writes it to the source's registry item as `ingest_schedule`.

### 3. Bronze to silver

- Copy `deploy/glue/bronze-to-silver-business-counts.py` for time-series data or `deploy/glue/bronze-to-silver-mhclg-deprivation.py` for snapshot data. Both use `deploy/glue/lib/glue_common.py`: `start_job` and `configure_catalog` for setup, then `write_timeseries(spark, df, table, partition_col)` (replaces only the partitions in `df`) or `write_snapshot(spark, df, table)` (replaces every row in one commit). Don't write tables directly with `writeTo`, `DELETE FROM` or `ALTER TABLE` in the script.
- The write helpers create the table on first run and add new columns. A column missing from a run is kept and written as null. Pass `allow_drop=True` only when you mean to remove a column for good.
- In `deploy/terraform-live/52-glue-etl.tf`, add `"<dept>-<name>" = 2` to `local.bronze_to_silver_jobs`. The key is the script suffix after `bronze-to-silver-`, the value is the worker count (4 for the two largest sources). One `for_each` builds the S3 object and the job `${var.PrefixCode}-glue-bronze-to-silver-<dept>-<name>` from it, with `local.glue_default_args`, which loads `glue_common` through `--extra-py-files`. The ETL Step Function finds jobs by that name prefix and the platform facts list them. The Glue and Step Functions IAM policies already cover new jobs.

### 4. Gold fact table and registry

Add one dict to `TABLES` in `deploy/glue/lib/gold_tables.py`, copying `fact_pip`. It describes the table and the source's registry entry together:

- `gold_table`: `fact_<name>`. `silver_table`: the table the Glue script wrote.
- `columns`: a list of Spark SQL select expressions. Renames, casts and derived columns are all strings, e.g. `"CAST(calendar_year AS INT) AS calendar_year"`. Use `MONTH_LABEL.format(col="date_name")` for a `period_yyyymm` from a "January 2024" label. `filter` is an optional SQL condition. `partition` is `"calendar_year"` for time-series data; omit it for a snapshot.
- A table that needs a join or an aggregate names a `build` method of `Gold` in `deploy/glue/lib/gold_build.py` instead of `columns`, like `fact_crime`.
- `source_id`, `department`, `name`, `api_url`, `update_frequency`, `bronze_s3_prefix` (the path the Lambda writes to) and `glue_job_name` (the job name without `{prefix}-glue-`) are the registry entry, written when the table builds.
- `attribution`: the statements the provider specifies under the Open Government Licence, as a list. Check the provider's licence page, then reuse a constant at the top of the file: `ONS`, `HMLR`, or `OGL` (the licence's default sentence) when the provider has no wording of its own. Statements are shown once each, deduplicated across the sources an answer used. The webapp footer, `/attribution` page, "Datasets used" panel and the gateway tools all read it from the registry, and the README table should list the new source too.
- The year range comes from `calendar_year`. Set `year` to another SQL expression, or a `("2025", "2025")` pair for a point-in-time dataset.
- `view_columns`, if the source adds columns to the area views (step 5).
- `prompt`, the data agent's notes on the table (step 6).
- `dim_time` spans the years of nine core sources, listed in `build_dim_time`. If your source covers years outside them, add it there.
- The job builds every table unless started with `--TABLES fact_a,fact_b`, which builds those and the dimensions only.

Superseded geography codes:

- Fetch current boundaries where the source offers them. For NOMIS that's `geography=TYPE424`, which returns the back series on April 2023 council areas.
- Old codes are resolved from `la_code_history`, a silver table built from the ONS Code History Database. Don't keep code mappings in scripts.
- Recoded councils (same area, new code) get the current code automatically in every gold table with `geography_code`.
- Merged councils need a decision per table. For counts and totals, set `merge_measures` to the columns to sum, like `fact_road_traffic`, which moves old rows onto the new council. Rates and averages can't be summed. Leave them on the old code.

### 5. Redshift

- Add `deploy/lambda/redshift-setup/sql/refresh/NN-rs-fact-<name>.sql` with an unused `NN` between 01 and 98:
  ```sql
  CREATE MATERIALIZED VIEW rs_fact_<name> AS
  SELECT
      geography_code::VARCHAR(20),
      calendar_year::INT,
      value::BIGINT
  FROM gold.fact_<name>;
  ```
  Cast every column. `99-grant-rs-tables.sql` grants on all tables; no grant is needed.
- If the source has area-level metrics, add them to the views in `sql/gold/`:
  - `06-mv-area-overview.sql`: the latest value per area plus a companion `<source>_year`, `<source>_period` or `<source>_snapshot_date` column, which lets the agent say which period a figure is from
  - `07-mv-area-timeseries.sql`: the yearly value, and extend the trailing `OR ... IS NOT NULL` filter
  - `08-mv-uk-summary.sql`: a national total, if it's a headline figure
- The Lambda strips full-line `--` comments, splits files on `;` and runs `str.format()` on each statement. Keep semicolons out of trailing comments and string literals, and write literal braces as `{{` and `}}`.

### 6. Agents

- The data agent's notes go in a `prompt` string on the `TABLES` entry in `gold_tables.py` (step 4), one line per note: valid values for filter columns, which JOIN supplies missing names or codes, the time column, whether it's time-series or a snapshot, any aggregation rule (for example, never SUM a monthly stock measure), and the default filters. `deploy/agent-main/app.py` renders them under the table's columns, which it reads from Redshift with the year ranges and the view columns. Rebuilt hourly and on each deploy.
- `deploy/agent-shared-tools/run_sql.py`: add `fact_<name>` and `rs_fact_<name>` to `_KNOWN_TABLES`. Queries work without it, but the chat "datasets used" panel and the dashboard won't credit the source.
- `deploy/agent-shared-tools/summarise_area.py`: add new view columns to `NATIONAL_SQL` and `TIMESERIES_SQL`, to `LOWER_IS_BETTER` if lower is better, and to `RADAR_METRICS` if it belongs on the radar chart. Make the same change in `deploy/lambda/gw-summarise-area/handler.py`, which serves the MCP gateway.
- `deploy/agent-walkthrough/walkthrough_prompt.py`: add `rs_fact_<name>` to the Facts list under `## Data warehouse`.
- `deploy/terraform-live/85-platform-facts.tf`: add the Lambda to `ingestion.lambdas`. The walkthrough agent reports it; the Glue job is already listed from the `for_each`.

### 7. Web app (optional)

- Add sample questions to `/example-questions` in `deploy/webapp/server.js`.
- `deploy/webapp/views/chat.html` states a dataset count in its intro text. Update it if it no longer matches.

### 8. Deploy and load

1. Grep for the new source's names (`ingest_<dept>_<name>`, `bronze-to-silver-<dept>-<name>`, `fact_<name>`, `rs_fact_<name>`) and confirm every file in steps 1–6 has them. Then push to your deploy branch. The pipeline deploys the Lambdas, Glue scripts and SQL files. The ETL Step Function runs the Redshift SQL, not Terraform.
2. Land the data in bronze:
   ```bash
   aws stepfunctions start-execution --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-ingest-all --input '{"sources": ["<router key>"]}' --profile $AWS_PROFILE --region $AWS_REGION
   ```
3. Run the ETL Step Function, or wait for its 05:00 UTC run. It finds the new bronze-to-silver job by its name prefix, runs it, builds gold and writes the registry item. Later runs change-detect the source like any other:
   ```bash
   aws stepfunctions start-execution --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-etl-to-gold --profile $AWS_PROFILE --region $AWS_REGION
   ```
4. Check the registry item has `row_count` and `max_year`, and that `rs_fact_<name>` exists in Redshift. A SQL error in your new files fails the Step Function. A gold table that doesn't exist yet doesn't: the Redshift setup Lambda logs `STAND-IN` and creates an empty `rs_fact_<name>` with the same columns, and the area views build with nulls for the source. That only works if every column in the refresh SQL is `name::TYPE` or `TRY_CAST(name AS TYPE) AS name`. A failed bronze-to-silver job or gold fact block fails the run at the end, after everything else has built. Check the Glue job runs, the gold job's log and the `{prefix}-lambda-redshift-setup` log if anything is absent.

## Remove a data source

1. Reverse the steps above, then grep for the source's names to confirm nothing is left. Also remove the source's sample questions from `deploy/webapp/server.js` and `deploy/webapp/views/chat.html`. The browser smoke test (`tests/browser_smoke_test.py`) only needs changing if you remove deprivation.
2. Push, then run the ETL Step Function with the input `{"full": true}`, or wait for the Sunday full run. Its refresh step drops every `rs_*` and `mv_*` object and rebuilds from the SQL files, which removes the table.
3. Delete the leftover gold and silver tables and the registry item. The silver table name is the one the Glue script wrote.
   ```bash
   aws s3tables delete-table --table-bucket-arn arn:aws:s3tables:${AWS_REGION}:${ACCOUNT_ID}:bucket/${PREFIX_CODE}-datalake-gold-${ACCOUNT_ID} --namespace gold --name fact_<name> --profile $AWS_PROFILE --region $AWS_REGION
   aws s3tables delete-table --table-bucket-arn arn:aws:s3tables:${AWS_REGION}:${ACCOUNT_ID}:bucket/${PREFIX_CODE}-datalake-silver-${ACCOUNT_ID} --namespace silver --name <silver_table> --profile $AWS_PROFILE --region $AWS_REGION
   aws dynamodb delete-item --table-name ${PREFIX_CODE}-data-source-registry --key '{"source_id": {"S": "<source-id>"}}' --profile $AWS_PROFILE --region $AWS_REGION
   ```
4. If no other source uses its API key, remove the key from the secret with `put-secret-value`. `dwp_stat_xplore` is shared by four DWP sources.

## Reference

### Shell variables

The commands above use the variables from the post-deploy guide:

```bash
export AWS_PROFILE=<your-aws-profile> AWS_REGION=eu-west-2 PREFIX_CODE=govdata
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

### Redshift setup Lambda (`{prefix}-lambda-redshift-setup`)

Workgroup `{prefix}-workgroup`, database `analytics`.

Gold tables in Amazon S3 Tables are read through the Spectrum external schema `gold`, which points at the Glue resource link `{prefix}_gold_s3tables`. Each `rs_*` object is a materialized view over `gold.*`, apart from `rs_fact_hpi` and `rs_fact_nhs_ods`, which are CTAS tables. The `mv_*` views join the `rs_*` objects. All of them are stored in Redshift.

Actions:

- `warmup`: runs `SELECT 1` to wake the workgroup.
- `refresh`: drops every `rs_*` and `mv_*` object in `public` (listed from `SVV_MV_INFO` and `pg_tables`), recreates the `gold` external schema, runs `sql/refresh/` in file order, then grants.
- `gold` (the default): creates the external schema if missing, rebuilds the views in `sql/gold/06`–`08`, then grants.

Any other action raises an error. For a full rebuild, run `refresh` then `gold`, as the ETL Step Function does. A failed SQL statement also raises, after the rest of the run completes. In `refresh`, an `rs_*` object whose gold table isn't loaded yet (`EntityNotFoundException` or `relation ... does not exist`) is created as an empty stand-in table, logged as `STAND-IN`, and doesn't fail the run. In `gold`, a view that can't find an `rs_*` object fails the run, except on a fresh deployment before the first refresh.

### ETL Step Function (`{prefix}-sfn-etl-to-gold`)

Runs at 05:00 UTC Monday to Saturday (`{prefix}-schedule-etl-to-gold`), as a full run at 05:00 UTC on Sunday (`{prefix}-schedule-etl-to-gold-full`, input `{"full": true}`), and on demand.

1. DetectChanges: on a fresh deployment, queues every `{prefix}-glue-bronze-to-silver-*` job. Otherwise it queues registry sources whose bronze files are newer than `silver_last_processed`, plus any `{prefix}-glue-bronze-to-silver-*` job with no registry item yet (a newly added source). It also returns the scope: full on a fresh deployment, a new source or `{"full": true}`, otherwise the queued sources' `gold_tables` from the registry plus the dimensions.
2. AnyWork: ends the run when nothing is queued and it isn't full. Gold and Redshift are left as they are.
3. WarmupRedshift: wakes the workgroup. A failure here continues to the next state.
4. AnyChanges: skips to SilverToGold when no job is queued (a full run with nothing new).
5. RunBronzeToSilver: runs the queued Glue jobs, five at a time. A failed job is recorded and the run continues. A successful one has its `silver_last_processed` stamped by `mark-silver-processed`.
6. SilverToGold: the dimensional model job with `--TABLES` from the scope (`all` on a full run), which also writes the registry. It sets `silver_last_processed` only on a source's first build. It fails at the end if any table failed, after committing the ones that built.
7. RedshiftRefresh: `action=refresh` with the scope's `rs_*` objects, or every object on a full run. Runs even if SilverToGold failed.
8. RedshiftGold: `action=gold`.
9. CheckFailures: fails the run if SilverToGold failed or any bronze-to-silver job failed, naming the failed sources.

A change to the gold build or the refresh SQL reaches the data at the Sunday full run, or straight away with `{"full": true}`. A source whose gold build failed in a scoped run is rebuilt on Sunday.

### API keys

`{prefix}-api-keys-public` in Secrets Manager holds a JSON object of API keys. It's never in git. Terraform seeds it with a `dwp_stat_xplore` placeholder and ignores later changes. Add keys with the CLI. `put-secret-value` replaces the whole object. Include the existing keys:

```bash
aws secretsmanager put-secret-value --secret-id ${PREFIX_CODE}-api-keys-public --secret-string '{"dwp_stat_xplore": "<key>", "<new_key>": "<key>"}' --profile $AWS_PROFILE --region $AWS_REGION
```

### Data source registry

DynamoDB `{prefix}-data-source-registry`, keyed on `source_id`. After each successful gold build, the gold job writes the static fields from the table's entry in `gold_tables.py` plus `min_year`, `max_year`, `row_count` and `silver_last_processed`. Nothing in Terraform writes registry items.

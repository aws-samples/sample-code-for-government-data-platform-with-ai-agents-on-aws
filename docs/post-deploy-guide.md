# Post-deploy guide

A freshly deployed platform has no data. This guide loads it in three steps: ingest every source, run the ETL, check the result. It then covers the schedules, cost tags and how to connect an MCP client.

Every command below uses these shell variables. Set them first:

```bash
export AWS_PROFILE=<your-aws-profile> AWS_REGION=eu-west-2 PREFIX_CODE=govdata
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

## 1. Ingest data

> [!WARNING]
> The DWP Stat-Xplore API key must already be in Secrets Manager (README step 7). Without it, four sources fail.

Pull every source into bronze:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-ingest-all \
  --input '{"sources": ["all"]}' \
  --profile $AWS_PROFILE --region $AWS_REGION
```

Two sources take much longer than the rest on a first run.

- Police crime fans out across 44 forces and 12 months.
- Land Registry downloads one CSV of about 200 MB for every year since 1995.

Later runs are faster. Most sources overwrite bronze with their full history each time.

### Check it worked

Each source is retried up to three times, because publishers' APIs return the occasional error or timeout. A source that still fails doesn't stop the others. The run completes, then reports as failed and names the sources that didn't land:

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-ingest-all \
  --max-items 1 --query 'executions[0].[status,executionArn]' --output text --profile $AWS_PROFILE --region $AWS_REGION
aws stepfunctions describe-execution --execution-arn <arn> --query cause --output text --profile $AWS_PROFILE --region $AWS_REGION
```

A failed run reads `Sources failed after retries: ["universal-credit"]. The other sources landed in bronze.` Re-run just those sources with `--input '{"sources": ["universal-credit"]}'`.

To run specific sources only:

```bash
--input '{"sources": ["geography", "hmrc-trade", "gva"]}'
```

The source keys are the keys of `local.ingest_sources` in `deploy/terraform-live/20-ingest-orchestrator.tf`.

### Ingestion patterns

| Pattern | Sources | How it works |
|---------|---------|--------------|
| Step Function fan-out | crime, land-registry | Parallel Lambda invocations, one per force or per year |
| Single Lambda, paged NOMIS | claimant-count, employment, aps, population | Pages of 25,000 rows with `recordoffset`, on April 2023 boundaries |
| Single Lambda, full overwrite | jobs-density, business-counts, geography, deprivation | One API call, overwrite bronze |
| Single Lambda, versioned | wellbeing, earnings, schools, school-detail, gva, ons-hpi, births-deaths | ONS or DfE version check, new file per version |
| Single Lambda, paginated | road-traffic, hmrc-trade, nhs-rtt, nhs-ods, defra-air-quality, mhclg-spending | Paginated API, several requests |
| Single Lambda, API key | universal-credit, housing-benefit, cilif, pip | DWP Stat-Xplore key from Secrets Manager |

Land Registry skips years already in bronze. Pass `{"force": true}` to re-download them all.

## 2. Run the ETL

When ingestion has finished, run the ETL:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-etl-to-gold \
  --profile $AWS_PROFILE --region $AWS_REGION
```

The ETL transforms bronze into silver and gold tables, then rebuilds the Redshift views from gold. The first run builds everything. Later runs only process sources with new bronze data, and end straight away if there are none. The [architecture guide](ARCHITECTURE.md) lists the steps.

## 3. Check the result

Check the area views exist and have rows. The Redshift Data API is asynchronous. Run the query, wait for it, then read the result:

```bash
ID=$(aws redshift-data execute-statement \
  --workgroup-name ${PREFIX_CODE}-workgroup --database analytics \
  --sql "SELECT 'mv_area_overview' AS object, COUNT(*) AS rows FROM mv_area_overview
         UNION ALL SELECT 'mv_area_timeseries', COUNT(*) FROM mv_area_timeseries
         UNION ALL SELECT 'mv_uk_summary', COUNT(*) FROM mv_uk_summary
         UNION ALL SELECT 'rs_* objects', COUNT(DISTINCT table_name) FROM svv_columns WHERE table_schema = 'public' AND table_name LIKE 'rs\\_%'" \
  --profile $AWS_PROFILE --region $AWS_REGION --query Id --output text)
until aws redshift-data describe-statement --id $ID --query Status --output text --profile $AWS_PROFILE --region $AWS_REGION | grep -qE 'FINISHED|FAILED|ABORTED'; do sleep 5; done
aws redshift-data describe-statement --id $ID --query '[Status, Error]' --output text --profile $AWS_PROFILE --region $AWS_REGION
aws redshift-data get-statement-result --id $ID --query 'Records[*].[[0].stringValue, [1].longValue]' --output text --profile $AWS_PROFILE --region $AWS_REGION
```

The first query after an idle spell is slower while the workgroup wakes. A good result is `FINISHED` and four rows like these, in any order. The counts grow as sources are added:

```
FINISHED	None
rs_* objects	30
mv_area_timeseries	10466
mv_area_overview	318
mv_uk_summary	1
```

`mv_area_overview` has one row per English and Welsh council.

If the status is `FAILED` with `relation "mv_area_overview" does not exist`, the ETL hasn't finished or its RedshiftGold step failed. Check the `${PREFIX_CODE}-sfn-etl-to-gold` execution.

The data is now ready to query in the web app.

## Schedules

All times are UTC. EventBridge Scheduler runs them, defined in Terraform.

| Schedule | Resource | Cron | Notes |
|----------|----------|------|-------|
| ETL | `sfn-etl-to-gold` | `0 5 ? * MON-SAT *` | Rebuilds only the sources with new bronze data, or nothing |
| ETL, full | `sfn-etl-to-gold` with `{"full": true}` | `0 5 ? * SUN *` | Rebuilds every table |
| Redshift warmup | `redshift-setup` (warmup) | `0/4 8-17 ? * MON-FRI *` | Off by default. `SELECT 1` every 4 minutes to keep RPUs warm when `RedshiftWarmupEnabled = true`. The RPU-hours are billed |
| Ingest sources | `schedule-ingest-<key>` | `schedule` in `local.ingest_sources` | 14 sources at 06:00 UTC, a few days after each publisher's release. Each source's registry item records its cron as `ingest_schedule` |

Ingestion schedules run on their own. The ETL picks up new bronze data through change detection.

Terraform runs the Redshift setup Lambda once, on the first deploy, before any data is loaded. After that, only the ETL state machine rebuilds the `rs_*` and `mv_*` objects. A deploy that changes the gold build or the SQL files takes effect at the Sunday full run. To rebuild straight away, start a full run:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:${PREFIX_CODE}-sfn-etl-to-gold \
  --input '{"full": true}' \
  --profile $AWS_PROFILE --region $AWS_REGION
```

Ingestion and the ETL are safe to re-run at any time. To add a source, follow the checklist in `.kiro/steering/data-sources.md`. Container images are rebuilt in every pipeline run.

## Cost allocation tags (optional)

Every resource is tagged with `solution`, `codeblock` and `resourcetype`. To filter costs by those tags in Cost Explorer, activate them under Billing and Cost Management, Cost allocation tags. Do this about a day after the first deploy. Tags only appear there once they show up in billing data. In AWS Organizations, do it from the management account.

## Connect through MCP

The AgentCore Gateway exposes four MCP tools: `query_data`, `describe_schema`, `summarise_area` and `list_datasets`. Kiro, or any MCP client, can call them.

The gateway uses IAM auth. Every request must be SigV4-signed with the caller's AWS credentials. MCP clients talk to local servers over stdio. [MCP Proxy for AWS](https://github.com/aws/mcp-proxy-for-aws) bridges that gap: it runs on the client machine, signs each request and forwards it to the gateway. It needs [uv](https://docs.astral.sh/uv/getting-started/installation/).

Get the gateway URL:

```bash
aws bedrock-agentcore-control list-gateways --profile $AWS_PROFILE --region $AWS_REGION --query "items[?name=='${PREFIX_CODE}-mcp-gateway'].gatewayId" --output text
aws bedrock-agentcore-control get-gateway --gateway-identifier <gateway-id> --profile $AWS_PROFILE --region $AWS_REGION --query gatewayUrl --output text
```

For Kiro, copy the template and fill in `<gateway-url>`, `<your-aws-profile>` and the region:

```bash
mkdir -p .kiro/settings && cp .kiro/mcp.json.template .kiro/settings/mcp.json
```

Other MCP clients take the same `command` and `args`. The proxy reads fresh credentials on every request. After `aws sso login` or a credential refresh, the next call works.

The caller's IAM identity needs `bedrock-agentcore:InvokeGateway` on the gateway. Anyone in the account with that permission can query the platform's data through it.

# Platform facts for the walkthrough agent: public resource names and design facts only, no account id, secret or state

locals {
  # One entry per inference profile prefix (us., eu., apac.), the lookup is on the full id
  model_names = {
    "us.anthropic.claude-sonnet-4-6"              = "Claude Sonnet 4.6"
    "eu.anthropic.claude-sonnet-4-6"              = "Claude Sonnet 4.6"
    "apac.anthropic.claude-sonnet-4-6"            = "Claude Sonnet 4.6"
    "us.anthropic.claude-haiku-4-5-20251001-v1:0" = "Claude Haiku 4.5"
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0" = "Claude Haiku 4.5"
    "us.anthropic.claude-haiku-4-5"               = "Claude Haiku 4.5"
    "eu.anthropic.claude-haiku-4-5"               = "Claude Haiku 4.5"
  }
  model_smart = { id = var.BedrockModelSmart, name = lookup(local.model_names, var.BedrockModelSmart, var.BedrockModelSmart) }
  model_fast  = { id = var.BedrockModelFast, name = lookup(local.model_names, var.BedrockModelFast, var.BedrockModelFast) }

  platform_facts = {
    region = var.Region
    prefix = var.PrefixCode

    ingestion = {
      orchestrator  = aws_sfn_state_machine.ingest_all.name
      bronze_bucket = module.datalake.bucket_id
      bronze_format = "Raw JSON and CSV from the source APIs, kept unchanged"
      lambdas = [
        module.ingest_ons_wellbeing.function_name,
        module.ingest_ons_population.function_name,
        module.ingest_dfe_school_performance.function_name,
        module.ingest_dfe_school_detail.function_name,
        module.ingest_ons_earnings.function_name,
        module.ingest_geography_reference.function_name,
        module.ingest_nomis_claimant_count.function_name,
        module.ingest_ons_employment.function_name,
        module.ingest_mhclg_deprivation.function_name,
        module.ingest_dwp_universal_credit.function_name,
        module.ingest_dft_road_traffic.function_name,
        module.ingest_nomis_aps.function_name,
        module.ingest_ons_gva.function_name,
        module.ingest_hmrc_trade.function_name,
        module.ingest_nhs_rtt.function_name,
        module.ingest_nhs_ods.function_name,
        module.ingest_ons_hpi.function_name,
        module.ingest_defra_air_quality.function_name,
        module.ingest_mhclg_spending.function_name,
        module.ingest_jobs_density.function_name,
        module.ingest_business_counts.function_name,
        module.ingest_ons_births_deaths.function_name,
        module.ingest_dwp_housing_benefit.function_name,
        module.ingest_dwp_cilif.function_name,
        module.ingest_dwp_pip.function_name,
      ]
      step_functions = [
        aws_sfn_state_machine.police_ingestion.name,
        aws_sfn_state_machine.land_registry_ingestion.name,
      ]
    }

    transformation = {
      etl_pipeline       = aws_sfn_state_machine.etl_to_gold.name
      silver_table_store = aws_s3tables_table_bucket.silver.name
      gold_table_store   = aws_s3tables_table_bucket.gold.name
      table_format       = "Apache Iceberg on Amazon S3 Tables"
      silver_to_gold     = aws_glue_job.silver_to_gold.name
      bronze_to_silver   = values(aws_glue_job.bronze_to_silver)[*].name
    }

    serving = {
      warehouse     = "Amazon Redshift Serverless"
      workgroup     = aws_redshiftserverless_workgroup.main.workgroup_name
      database      = aws_redshiftserverless_namespace.main.db_name
      serving_views = ["mv_area_overview", "mv_area_timeseries", "mv_uk_summary"]
      read_path     = "S3 Tables gold, read through Redshift Spectrum via a Glue external schema into rs_* materialised views stored in Redshift, then joined into mv_* materialised views for area profiles, timeseries and the UK summary"
      warmup        = var.RedshiftWarmupEnabled ? "EventBridge Scheduler keeps RPUs warm Mon-Fri 8am-6pm UTC" : "off; the workgroup wakes on first query"
    }

    agents = {
      data = {
        runtime = "${var.PrefixCode}_agent"
        models = {
          smart   = local.model_smart
          fast    = local.model_fast
          routing = "The data agent uses the fast model for simple lookups and the smart model for complex multi-step questions. Model selection happens inside the agent, not in Terraform."
        }
        tools = ["run_sql (read-only SELECT)", "describe_schema", "create_chart", "create_map", "create_choropleth", "summarise_area", "get_uk_facts"]
      }
      walkthrough = {
        # The name as a string: the walkthrough runtime reads this file, and referencing its attribute would be a cycle
        runtime = "${var.PrefixCode}_walkthrough"
        model   = local.model_smart
      }
      geospatial = {
        runtime = "${var.PrefixCode}_geospatial"
        models  = { smart = local.model_smart, fast = local.model_fast, routing = "The fast model answers area overviews, the smart model change detection." }
        design  = "The area of interest is the map view the user is looking at. Two bounded tools, analyse_area and compare_change, take only an index from a short list and dates; they search the Earth Search STAC API, pick a scene by coverage, cloud and date, read Sentinel-2 or Landsat bands and compute spectral indices for vegetation, water, built-up surfaces, burn severity and surface temperature. Every result names its scenes, dates and cloud cover. No model-written code runs. The runtime role is limited to Bedrock, the guardrail, logs and reading the USGS Landsat bucket."
        tools   = ["analyse_area", "compare_change"]
      }
      framework      = "Strands Agents on Amazon Bedrock AgentCore Runtime, streaming the AG-UI protocol"
      context_window = "The browser strips chart, map and SQL payloads from past messages and caps each at 3000 characters. The agent keeps the last 20 messages, simple questions go to the smaller model, and a summarising conversation manager compacts older messages if a turn still overflows."
      mcp_gateway = {
        name  = aws_bedrockagentcore_gateway.main.name
        tools = ["list_datasets", "describe_schema", "query_data (read-only, same SQL guard as the agents)", "summarise_area"]
        auth  = "AWS IAM (SigV4): any principal in this account allowed bedrock-agentcore:InvokeGateway"
        use   = "Lets external MCP clients such as Kiro or Amazon Quick query the same serving layer the agents use"
      }
      guardrail = var.BedrockGuardrailEnabled ? "Bedrock guardrail on the data and geospatial agents: content filters, a denied topic for personal medical, legal and financial advice, blocking of AWS credentials, and anonymisation of email addresses and phone numbers. The walkthrough agent runs without it." : "off"
    }

    web = {
      hosting   = "Amazon ECS on AWS Fargate behind an Application Load Balancer and Amazon CloudFront"
      domain    = aws_cloudfront_distribution.webapp.domain_name
      access    = "Amazon Cognito sign-in handled by the webapp (OpenID Connect with PKCE); users are created by an administrator"
      maps      = "MapLibre GL JS with Amazon Location Service map tiles, proxied through the webapp"
      dashboard = "Kiosk dashboard of platform usage and data coverage, its own ECS Fargate service on the /dashboard path"
    }

    # Each entry names something this platform deliberately does not include.
    not_included = [
      "No street-level crime: police data is counted by local authority, crime type and month only",
      "No object detection or SageMaker endpoints",
      "No model-written code execution: the data and walkthrough agents' tools only run read-only SQL, and the geospatial agent's two tools take an index and dates",
      "No Fingertips (PHE) health indicators and no Amazon EMR",
    ]

    # One entry per step of adding a source, matching the steering checklist
    adding_a_source = [
      "Ingestion Lambda, with one entry in the ingest source list (local.ingest_sources), which registers it with the router, the ingest Step Function's IAM and, if it has a cron, a schedule",
      "Bronze-to-silver Glue job named with the bronze-to-silver prefix, so the ETL pipeline can find it",
      "One entry in the gold job's table list (deploy/glue/lib/gold_tables.py): the silver table, the columns to select, the registry fields including view_columns, and the data agent's prompt notes",
      "An rs_fact_* materialised view over the gold table, built by the Redshift setup Lambda",
      "Columns in the area materialised views (overview, timeseries and UK summary), with a year or period column, if it has area-level metrics",
      "The table in the SQL tool's known-tables list and its metrics in the area summary tool; the data agent reads the columns from Redshift and the notes from the gold table list",
      "The Lambda and Glue job added to the platform facts the walkthrough agent reports, and sample questions in the web app",
      "Run the ETL Step Function once. It finds the new Glue job by its name prefix, builds the source, and the gold job writes row counts and year ranges to the registry. After that the daily ETL run picks up new data",
    ]
  }
}

resource "aws_s3_object" "platform_facts" {
  bucket       = module.datalake.bucket_id
  key          = "platform/facts.json"
  content      = jsonencode(local.platform_facts)
  content_type = "application/json"

  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.datalake.arn

  tags = {
    Name         = "${var.PrefixCode}-s3object-platform-facts"
    resourcetype = "storage"
    codeblock    = "85-platform-facts"
  }
}
